"""Application settings, read from environment variables / the .env file."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str = ""
    database_name: str = "neerus"
    collection_name: str = "inventory"
    # The inventory has no "status" field, so status is computed from quantity:
    #   quantity <= 0          -> out_of_stock
    #   quantity <= threshold  -> low_stock
    #   otherwise              -> in_stock
    low_stock_threshold: int = 20            # applied to the total across all stores
    low_stock_threshold_per_store: int = 3   # applied when a single store is selected
    frontend_origin: str = "http://localhost:5173"
    write_api_key: str = ""                  # empty = write endpoints disabled


@lru_cache
def get_settings() -> Settings:
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        database_name=os.getenv("DATABASE_NAME") or "neerus",
        collection_name=os.getenv("COLLECTION_NAME") or "inventory",
        low_stock_threshold=int(os.getenv("LOW_STOCK_THRESHOLD") or 20),
        low_stock_threshold_per_store=int(os.getenv("LOW_STOCK_THRESHOLD_PER_STORE") or 3),
        frontend_origin=os.getenv("FRONTEND_ORIGIN") or "http://localhost:5173",
        write_api_key=os.getenv("WRITE_API_KEY", ""),
    )
