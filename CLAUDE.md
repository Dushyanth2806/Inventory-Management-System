# Neerus Inventory API

FastAPI backend (Python) over an existing MongoDB Atlas database. Backend only; no frontend was built. Deployed to Render via `render.yaml`.

## Run / test (from `backend/`)
```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000     # docs at /docs
pytest -q                                  # 14 tests, in-memory mongomock, never touches live DB
```
Setup: `python -m venv .venv`, `pip install -r requirements.txt`, copy `.env.example` to `.env`.

## Layout
- `main.py`: app, CORS (only `FRONTEND_ORIGIN`), exception handlers, `/api/health`
- `config.py`: `Settings` dataclass from `.env` (cached `get_settings()`)
- `database.py`: cached `MongoClient` (5s server selection timeout), `get_db()`
- `schemas.py`: Pydantic `ItemCreate` / `ItemUpdate` (`extra="forbid"`)
- `routers/inventory.py`: thin HTTP layer, `/api/inventory/*`, API-key guard for writes
- `services/inventory_service.py`: all logic and MongoDB access
- `tests/test_api.py`: critical-path tests
- `discover.py`: read-only script that lists DB collections and field names
- `../render.yaml`: Render config (rootDir `backend`)

## Database (live, shared with other apps)
- DB `neerus`, collection `inventory` (222 docs). Other collections (`stores`, `suppliers`, `sales`, `orders`, `transfers`, ...) are not ours; only `stores` and `suppliers` are read (lookups).
- **Live data**: sales and transfers write to it continuously. Never drop, bulk-overwrite or change schema. No indexes exist beyond `_id`; do not create any without approval.
- Document: `_id` == `id` (**int**, not ObjectId), `sku` (unique in practice), `name`, `type` (15 values), `department` (Women/Men/Kids; no shoes), `category`, `subCategory`, `style`, `fabric`, `occasion`, `colour`, `price`, `cost`, `suppliers` (list of supplier int ids), `stock` (object `{store name: qty}`, 7 stores). `size`/`sizes` are null, so omitted.

## Key behaviours
- **No status field exists.** Status is computed from quantity: `<=0` out_of_stock, `<=threshold` low_stock, else in_stock. Threshold is `LOW_STOCK_THRESHOLD` (20, total over all stores) or `LOW_STOCK_THRESHOLD_PER_STORE` (3) when a `store` param is given. Item `quantity` = quantity in that scope; `total_stock` is always the all-store sum.
- Endpoints: `GET /api/inventory`, `/search?q=`, `/filter` (q, department, category, type, store, status, sort_by, order), `/stats`, `/meta`, `/{item_id}`; `POST`, `PUT /{id}`, `DELETE /{id}`. Fixed paths must be declared before `/{item_id}`.
- Reads load up to `MAX_SCAN` (5000) docs, shape and filter by status in Python, then paginate (limit max 100). Fine for hundreds of items; revisit with aggregation if it grows large.
- **Writes** need header `X-API-Key` equal to `WRITE_API_KEY` (empty key = writes disabled, 403). `PUT` uses `$set` of only the sent fields; `stock` is merged per store (`stock.<store>`) so concurrent sales updates to other stores are not overwritten. Create assigns `max(_id)+1`, validates department/stores/suppliers exist and SKU uniqueness (409).
- Search text is `re.escape`d before use in `$regex`. DB errors map to generic 503/500 messages; the URI is never logged or returned.

## Environment (`backend/.env`, git-ignored; never commit or print)
`MONGODB_URI`, `DATABASE_NAME=neerus`, `COLLECTION_NAME=inventory`, `LOW_STOCK_THRESHOLD`, `LOW_STOCK_THRESHOLD_PER_STORE`, `FRONTEND_ORIGIN`, `WRITE_API_KEY`.

## Conventions
- Keep routers thin; put logic in the service. Service errors (`ItemNotFound` 404, `DuplicateSku` 409, `InvalidInput` 422) are mapped in `main.py`.
- Tests override `get_db` / `get_settings` with mongomock; `/api/health` calls `get_db()` directly, so tests monkeypatch `main.get_db`.
- Test writes against mongomock only, not the live database.

## Open items
- The Atlas password was pasted into a chat; it should be rotated (update `.env` and Render).
- Atlas Network Access must allow Render's outbound IPs.
- Possible hardening: a unique index on `sku` (needs approval).
