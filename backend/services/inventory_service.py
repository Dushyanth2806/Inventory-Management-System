"""All inventory logic. Routers stay thin; this module talks to MongoDB.

Existing schema (neerus.inventory):
  _id == id (int), sku, name, type, department, category, subCategory, style, fabric,
  occasion, colour, price, cost, suppliers (list of supplier ids),
  stock (object: {store name: quantity}).
There is no status field, so stock status is computed (see config.Settings).
"""
import re
from typing import Optional

from pymongo.errors import DuplicateKeyError

from config import Settings

TEXT_FIELDS = ["sku", "name", "type", "department", "category", "subCategory",
               "style", "fabric", "occasion", "colour"]
SEARCH_FIELDS = ["name", "sku", "category", "subCategory", "type", "colour", "style"]
SORT_KEYS = {"name", "sku", "price", "quantity", "department"}
MAX_SCAN = 5000  # safety cap on documents read per request


class ItemNotFound(Exception):
    pass


class DuplicateSku(Exception):
    pass


class InvalidInput(Exception):
    pass


# ---------- helpers ----------

def total_qty(stock: Optional[dict]) -> int:
    return sum(v for v in (stock or {}).values() if isinstance(v, (int, float)))


def stock_status(qty: int, threshold: int) -> str:
    if qty <= 0:
        return "out_of_stock"
    return "low_stock" if qty <= threshold else "in_stock"


def _supplier_names(db) -> dict:
    return {s["_id"]: s.get("name") for s in db["suppliers"].find({}, {"name": 1})}


def store_names(db) -> list[str]:
    return sorted(s["name"] for s in db["stores"].find({}, {"name": 1}) if s.get("name"))


def _check_store(db, store: Optional[str]):
    if store and store not in store_names(db):
        raise InvalidInput(f"Unknown store '{store}'")


def _shape(doc: dict, suppliers: dict, settings: Settings, store: Optional[str]) -> dict:
    """Turn a raw document into the API shape. Missing fields become null, never invented."""
    stock = doc.get("stock") or {}
    total = total_qty(stock)
    if store:
        qty, limit = stock.get(store, 0), settings.low_stock_threshold_per_store
    else:
        qty, limit = total, settings.low_stock_threshold
    ids = doc.get("suppliers") or []
    item = {"id": doc["_id"]}
    item.update({f: doc.get(f) for f in TEXT_FIELDS})
    item.update({
        "price": doc.get("price"),
        "cost": doc.get("cost"),
        "stock": stock,
        "total_stock": total,
        "quantity": qty,                       # quantity in the selected scope (store or all)
        "stock_status": stock_status(qty, limit),
        "supplier_ids": ids,
        "supplier_names": [suppliers.get(i) or f"#{i}" for i in ids],
    })
    return item


def _mongo_filter(q=None, department=None, category=None, type_=None) -> dict:
    f: dict = {}
    if department:
        f["department"] = department
    if category:
        f["category"] = category
    if type_:
        f["type"] = type_
    if q:
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}  # user text is escaped, never executed
        f["$or"] = [{field: pattern} for field in SEARCH_FIELDS]
    return f


# ---------- reads ----------

def query_items(db, settings, *, q=None, department=None, category=None, type_=None,
                store=None, status=None, sort_by="name", order="asc", skip=0, limit=25) -> dict:
    if sort_by not in SORT_KEYS:
        raise InvalidInput(f"sort_by must be one of {sorted(SORT_KEYS)}")
    _check_store(db, store)
    suppliers = _supplier_names(db)
    docs = db[settings.collection_name].find(_mongo_filter(q, department, category, type_)).limit(MAX_SCAN)
    items = [_shape(d, suppliers, settings, store) for d in docs]
    if status:
        items = [i for i in items if i["stock_status"] == status]

    def key(i):
        v = i.get(sort_by)
        return (v is None, v.lower() if isinstance(v, str) else v)

    items.sort(key=key, reverse=(order == "desc"))
    return {"items": items[skip:skip + limit], "total": len(items), "skip": skip, "limit": limit}


def get_item(db, settings, item_id: int, store=None) -> dict:
    doc = db[settings.collection_name].find_one({"_id": item_id})
    if doc is None:
        raise ItemNotFound(f"No inventory item with id {item_id}")
    return _shape(doc, _supplier_names(db), settings, store)


def get_stats(db, settings, department=None, store=None) -> dict:
    _check_store(db, store)
    suppliers = _supplier_names(db)
    docs = db[settings.collection_name].find(_mongo_filter(department=department)).limit(MAX_SCAN)
    items = [_shape(d, suppliers, settings, store) for d in docs]

    def summarize(rows):
        return {
            "items": len(rows),
            "units": sum(r["quantity"] for r in rows),
            "low_stock": sum(r["stock_status"] == "low_stock" for r in rows),
            "out_of_stock": sum(r["stock_status"] == "out_of_stock" for r in rows),
            "inventory_value": sum(r["quantity"] * r["price"] for r in rows if r["price"] is not None),
        }

    by_dept: dict = {}
    for i in items:
        by_dept.setdefault(i["department"] or "Unassigned", []).append(i)
    return {
        **summarize(items),
        "scope": {"department": department, "store": store},
        "thresholds": {"total": settings.low_stock_threshold,
                       "per_store": settings.low_stock_threshold_per_store},
        "by_department": [{"department": d, **summarize(rows)} for d, rows in sorted(by_dept.items())],
    }


def get_meta(db, settings) -> dict:
    coll = db[settings.collection_name]
    types_by_dept = {}
    for d in coll.find({}, {"department": 1, "type": 1, "category": 1}):
        entry = types_by_dept.setdefault(d.get("department") or "Unassigned", {"types": set(), "categories": set()})
        if d.get("type"):
            entry["types"].add(d["type"])
        if d.get("category"):
            entry["categories"].add(d["category"])
    return {
        "departments": [{"name": n, "types": sorted(v["types"]), "categories": sorted(v["categories"])}
                        for n, v in sorted(types_by_dept.items())],
        "stores": store_names(db),
        "suppliers": [{"id": k, "name": v} for k, v in sorted(_supplier_names(db).items())],
        "thresholds": {"total": settings.low_stock_threshold, "per_store": settings.low_stock_threshold_per_store},
    }


# ---------- writes ----------

def _validate_refs(db, settings, data: dict):
    """Reject departments, stores or suppliers that don't already exist in the database."""
    if data.get("department"):
        known = coll_distinct(db, settings, "department")
        if data["department"] not in known:
            raise InvalidInput(f"Unknown department '{data['department']}'. Existing: {sorted(known)}")
    if data.get("stock"):
        stores = set(store_names(db))
        bad = [s for s in data["stock"] if s not in stores]
        if bad:
            raise InvalidInput(f"Unknown store(s): {bad}. Existing: {sorted(stores)}")
    if data.get("suppliers"):
        known_ids = set(_supplier_names(db))
        bad = [s for s in data["suppliers"] if s not in known_ids]
        if bad:
            raise InvalidInput(f"Unknown supplier id(s): {bad}")


def coll_distinct(db, settings, field):
    return set(db[settings.collection_name].distinct(field))


def _sku_taken(coll, sku: str, exclude_id: Optional[int] = None) -> bool:
    f: dict = {"sku": sku}
    if exclude_id is not None:
        f["_id"] = {"$ne": exclude_id}
    return coll.count_documents(f, limit=1) > 0


def create_item(db, settings, data: dict) -> dict:
    coll = db[settings.collection_name]
    _validate_refs(db, settings, data)
    if _sku_taken(coll, data["sku"]):
        raise DuplicateSku(f"SKU '{data['sku']}' already exists")
    for _ in range(3):  # retry if another writer grabs the same id first
        last = coll.find_one(sort=[("_id", -1)], projection={"_id": 1})
        new_id = (last["_id"] if last else 0) + 1
        try:
            coll.insert_one({"_id": new_id, "id": new_id, **data})
            return get_item(db, settings, new_id)
        except DuplicateKeyError:
            continue
    raise InvalidInput("Could not allocate a new id, please retry")


def update_item(db, settings, item_id: int, changes: dict) -> dict:
    coll = db[settings.collection_name]
    if not changes:
        raise InvalidInput("No fields to update")
    if coll.count_documents({"_id": item_id}, limit=1) == 0:
        raise ItemNotFound(f"No inventory item with id {item_id}")
    _validate_refs(db, settings, changes)
    if "sku" in changes and _sku_taken(coll, changes["sku"], exclude_id=item_id):
        raise DuplicateSku(f"SKU '{changes['sku']}' already exists")
    # Only touch the fields that were sent. Stock is set per store ("stock.Gachibowli")
    # so quantities of other stores, which live sales may be changing, are never overwritten.
    to_set = {k: v for k, v in changes.items() if k != "stock"}
    for store, qty in (changes.get("stock") or {}).items():
        to_set[f"stock.{store}"] = qty
    coll.update_one({"_id": item_id}, {"$set": to_set})
    return get_item(db, settings, item_id)


def delete_item(db, settings, item_id: int) -> None:
    if db[settings.collection_name].delete_one({"_id": item_id}).deleted_count == 0:
        raise ItemNotFound(f"No inventory item with id {item_id}")
