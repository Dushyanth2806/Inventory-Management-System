from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import (ConnectionFailure, OperationFailure, PyMongoError,
                            ServerSelectionTimeoutError)

from config import Settings, get_settings
from database import DatabaseNotConfigured, get_db
from routers import inventory
from services.inventory_service import DuplicateSku, InvalidInput, ItemNotFound

app = FastAPI(title="Neerus Inventory API", version="1.0.0")

# Only the frontend origin may call this API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)
app.include_router(inventory.router)


def _error(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": message})


@app.exception_handler(ItemNotFound)
async def _not_found(_: Request, e: ItemNotFound):
    return _error(404, str(e))


@app.exception_handler(DuplicateSku)
async def _duplicate(_: Request, e: DuplicateSku):
    return _error(409, str(e))


@app.exception_handler(InvalidInput)
async def _invalid(_: Request, e: InvalidInput):
    return _error(422, str(e))


@app.exception_handler(DatabaseNotConfigured)
async def _not_configured(_: Request, e: DatabaseNotConfigured):
    return _error(503, str(e))


# Database failures return safe, generic messages (the raw error could contain host details).
@app.exception_handler(PyMongoError)
async def _db_error(_: Request, e: PyMongoError):
    if isinstance(e, OperationFailure) and e.code in (13, 18):
        return _error(503, "Database rejected the request: check the database user's permissions/credentials.")
    if isinstance(e, (ServerSelectionTimeoutError, ConnectionFailure)):
        return _error(503, "Cannot reach MongoDB (timeout). Check your internet, the Atlas Network Access "
                           "IP allowlist, and MONGODB_URI.")
    return _error(500, "A database error occurred.")


@app.get("/api/health", tags=["health"])
def health(settings: Settings = Depends(get_settings)):
    try:
        db = get_db()
        db.command("ping")
        count = db[settings.collection_name].estimated_document_count()
        return {"status": "ok", "database": "connected", "inventory_items": count,
                "writes_enabled": bool(settings.write_api_key)}
    except DatabaseNotConfigured as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "not_configured", "detail": str(e)})
    except PyMongoError as e:
        hint = ("timeout / network access" if isinstance(e, (ServerSelectionTimeoutError, ConnectionFailure))
                else "authentication or permissions" if isinstance(e, OperationFailure) else "database error")
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable", "detail": hint})
