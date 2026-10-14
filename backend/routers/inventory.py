"""HTTP layer: validates parameters, checks the API key for writes, calls the service."""
import hmac
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from config import Settings, get_settings
from database import get_db
from schemas import ItemCreate, ItemUpdate
from services import inventory_service as svc

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

Status = Literal["in_stock", "low_stock", "out_of_stock"]


def require_api_key(x_api_key: Optional[str] = Header(None), settings: Settings = Depends(get_settings)):
    """Write endpoints need the secret from WRITE_API_KEY in the X-API-Key header."""
    if not settings.write_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Write operations are disabled (WRITE_API_KEY not set)")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.write_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key")


# NOTE: fixed paths (/search, /filter, /stats, /meta) must be declared before /{item_id}.

@router.get("", summary="List inventory (paginated)")
def list_inventory(
    skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
    sort_by: str = "name", order: Literal["asc", "desc"] = "asc",
    store: Optional[str] = Query(None, max_length=60),
    db=Depends(get_db), settings: Settings = Depends(get_settings),
):
    return svc.query_items(db, settings, store=store, sort_by=sort_by, order=order, skip=skip, limit=limit)


@router.get("/search", summary="Search name, SKU, category, type, colour, style")
def search_inventory(
    q: str = Query(..., min_length=1, max_length=100),
    skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
    store: Optional[str] = Query(None, max_length=60),
    db=Depends(get_db), settings: Settings = Depends(get_settings),
):
    return svc.query_items(db, settings, q=q, store=store, skip=skip, limit=limit)


@router.get("/filter", summary="Filter by department, category, type, store, stock status (and optional q)")
def filter_inventory(
    q: Optional[str] = Query(None, min_length=1, max_length=100),
    department: Optional[str] = Query(None, max_length=60),
    category: Optional[str] = Query(None, max_length=60),
    type: Optional[str] = Query(None, max_length=60),
    store: Optional[str] = Query(None, max_length=60),
    status: Optional[Status] = None,
    sort_by: str = "name", order: Literal["asc", "desc"] = "asc",
    skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
    db=Depends(get_db), settings: Settings = Depends(get_settings),
):
    return svc.query_items(db, settings, q=q, department=department, category=category, type_=type,
                           store=store, status=status, sort_by=sort_by, order=order, skip=skip, limit=limit)


@router.get("/stats", summary="Totals, low/out-of-stock counts, value, per-department breakdown")
def inventory_stats(
    department: Optional[str] = Query(None, max_length=60),
    store: Optional[str] = Query(None, max_length=60),
    db=Depends(get_db), settings: Settings = Depends(get_settings),
):
    return svc.get_stats(db, settings, department=department, store=store)


@router.get("/meta", summary="Departments, types, stores and suppliers that exist in the database")
def inventory_meta(db=Depends(get_db), settings: Settings = Depends(get_settings)):
    return svc.get_meta(db, settings)


@router.get("/{item_id}", summary="Get one item by its integer id")
def get_item(item_id: int, store: Optional[str] = Query(None, max_length=60),
             db=Depends(get_db), settings: Settings = Depends(get_settings)):
    return svc.get_item(db, settings, item_id, store)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_item(body: ItemCreate, db=Depends(get_db), settings: Settings = Depends(get_settings)):
    return svc.create_item(db, settings, body.model_dump())


@router.put("/{item_id}", dependencies=[Depends(require_api_key)],
            summary="Update only the fields sent (stock is merged per store)")
def update_item(item_id: int, body: ItemUpdate, db=Depends(get_db), settings: Settings = Depends(get_settings)):
    return svc.update_item(db, settings, item_id, body.model_dump(exclude_unset=True))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_api_key)])
def delete_item(item_id: int, db=Depends(get_db), settings: Settings = Depends(get_settings)):
    svc.delete_item(db, settings, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
