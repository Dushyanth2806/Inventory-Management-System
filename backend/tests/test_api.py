"""Critical-path tests. They use an in-memory fake MongoDB (mongomock), never the live database."""
import mongomock
import pytest
from fastapi.testclient import TestClient

from config import Settings, get_settings
from database import get_db
from main import app
from services.inventory_service import stock_status, total_qty

KEY = {"X-API-Key": "secret"}
STORES = ["Gachibowli", "Madhapur"]


def make_item(i, sku, name, dept, typ, stock):
    return {"_id": i, "id": i, "sku": sku, "name": name, "department": dept, "type": typ,
            "category": typ, "price": 100, "cost": 60, "suppliers": [1], "stock": stock}


@pytest.fixture()
def client():
    db = mongomock.MongoClient()["neerus"]
    db["inventory"].insert_many([
        make_item(1, "SKU-1", "Red Saree", "Women", "saree", {"Gachibowli": 30, "Madhapur": 10}),  # 40 in stock
        make_item(2, "SKU-2", "Blue Kurta", "Men", "menkurta", {"Gachibowli": 5, "Madhapur": 5}),   # 10 low
        make_item(3, "SKU-3", "Kids Frock", "Kids", "kidsfrock", {"Gachibowli": 0, "Madhapur": 0}),  # out
    ])
    db["stores"].insert_many([{"_id": s, "name": s} for s in STORES])
    db["suppliers"].insert_one({"_id": 1, "name": "Acme"})
    settings = Settings(write_api_key="secret", low_stock_threshold=20, low_stock_threshold_per_store=3)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---- pure logic ----
def test_status_thresholds():
    assert stock_status(0, 20) == "out_of_stock"
    assert stock_status(20, 20) == "low_stock"
    assert stock_status(21, 20) == "in_stock"
    assert total_qty({"a": 2, "b": 3, "c": None}) == 5


# ---- reads ----
def test_list_is_paginated_and_serialized(client):
    r = client.get("/api/inventory?limit=2")
    body = r.json()
    assert r.status_code == 200 and body["total"] == 3 and len(body["items"]) == 2
    assert body["items"][0]["supplier_names"] == ["Acme"]


def test_limit_is_capped(client):
    assert client.get("/api/inventory?limit=1000").status_code == 422


def test_get_item_and_invalid_ids(client):
    assert client.get("/api/inventory/1").json()["sku"] == "SKU-1"
    assert client.get("/api/inventory/999").status_code == 404
    assert client.get("/api/inventory/abc").status_code == 422


def test_search_and_regex_is_escaped(client):
    assert client.get("/api/inventory/search?q=saree").json()["total"] == 1
    assert client.get("/api/inventory/search?q=.*").json()["total"] == 0  # not treated as a regex
    assert client.get("/api/inventory/search").status_code == 422
    assert client.get("/api/inventory/search?q=nomatch").json()["items"] == []


def test_filter_by_department_status_and_store(client):
    assert client.get("/api/inventory/filter?department=Women").json()["total"] == 1
    assert client.get("/api/inventory/filter?status=out_of_stock").json()["items"][0]["sku"] == "SKU-3"
    assert client.get("/api/inventory/filter?status=bogus").status_code == 422
    # Per-store view: Gachibowli has 5 of the kurta, above the per-store threshold of 3
    item = client.get("/api/inventory/filter?store=Gachibowli&department=Men").json()["items"][0]
    assert item["quantity"] == 5 and item["stock_status"] == "in_stock"
    assert client.get("/api/inventory/filter?store=Nowhere").status_code == 422


def test_stats(client):
    s = client.get("/api/inventory/stats").json()
    assert (s["items"], s["units"], s["low_stock"], s["out_of_stock"]) == (3, 50, 1, 1)
    assert s["inventory_value"] == 5000
    assert {d["department"] for d in s["by_department"]} == {"Women", "Men", "Kids"}
    assert client.get("/api/inventory/stats?department=Women").json()["units"] == 40


def test_empty_collection(client):
    db = app.dependency_overrides[get_db]()
    db["inventory"].delete_many({})
    assert client.get("/api/inventory").json() == {"items": [], "total": 0, "skip": 0, "limit": 25}
    assert client.get("/api/inventory/stats").json()["items"] == 0


# ---- writes ----
NEW = {"sku": "SKU-9", "name": "New Dhoti", "type": "dhoti", "department": "Men", "category": "dhoti",
       "price": 250, "stock": {"Gachibowli": 4}}


def test_writes_require_api_key(client):
    assert client.post("/api/inventory", json=NEW).status_code == 401
    assert client.post("/api/inventory", json=NEW, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.delete("/api/inventory/1").status_code == 401
    assert client.put("/api/inventory/1", json={"name": "x"}).status_code == 401


def test_writes_disabled_without_configured_key(client):
    app.dependency_overrides[get_settings] = lambda: Settings(write_api_key="")
    assert client.post("/api/inventory", json=NEW, headers=KEY).status_code == 403


def test_create_validates_and_rejects_duplicates(client):
    r = client.post("/api/inventory", json=NEW, headers=KEY)
    assert r.status_code == 201 and r.json()["id"] == 4
    assert client.post("/api/inventory", json=NEW, headers=KEY).status_code == 409  # duplicate SKU
    for bad in ({**NEW, "sku": "X1", "price": -5}, {**NEW, "sku": "X2", "stock": {"Gachibowli": -1}},
                {**NEW, "sku": "X3", "stock": {"Mars": 1}}, {**NEW, "sku": "X4", "department": "Shoes"},
                {**NEW, "sku": "X5", "suppliers": [99]}, {**NEW, "sku": "X6", "bogus": 1},
                {k: v for k, v in NEW.items() if k != "name"}):
        assert client.post("/api/inventory", json=bad, headers=KEY).status_code == 422, bad


def test_update_changes_only_sent_fields(client):
    r = client.put("/api/inventory/1", json={"price": 999, "stock": {"Gachibowli": 1}}, headers=KEY)
    body = r.json()
    assert r.status_code == 200 and body["price"] == 999
    assert body["stock"] == {"Gachibowli": 1, "Madhapur": 10}  # other store untouched
    assert body["name"] == "Red Saree"
    assert client.put("/api/inventory/1", json={}, headers=KEY).status_code == 422
    assert client.put("/api/inventory/999", json={"name": "x"}, headers=KEY).status_code == 404
    assert client.put("/api/inventory/1", json={"sku": "SKU-2"}, headers=KEY).status_code == 409
    assert client.put("/api/inventory/1", json={"sku": "SKU-1"}, headers=KEY).status_code == 200  # own SKU ok


def test_delete(client):
    assert client.delete("/api/inventory/1", headers=KEY).status_code == 204
    assert client.get("/api/inventory/1").status_code == 404
    assert client.delete("/api/inventory/1", headers=KEY).status_code == 404


def test_database_failure_returns_safe_503(client, monkeypatch):
    from pymongo.errors import ServerSelectionTimeoutError

    def broken():
        raise ServerSelectionTimeoutError("mongodb+srv://user:pw@host: timed out")
    app.dependency_overrides[get_db] = broken
    monkeypatch.setattr("main.get_db", broken)  # /api/health calls get_db() directly
    r = client.get("/api/inventory")
    assert r.status_code == 503 and "pw" not in r.text and "mongodb+srv" not in r.text
    h = client.get("/api/health")
    assert h.status_code == 503 and "pw" not in h.text
