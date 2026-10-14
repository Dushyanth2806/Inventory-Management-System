"""MongoDB connection. The URI is only ever read from the environment and never logged."""
from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from config import get_settings


class DatabaseNotConfigured(Exception):
    """MONGODB_URI is missing."""


@lru_cache
def get_client() -> MongoClient:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise DatabaseNotConfigured("MONGODB_URI is not set in backend/.env")
    # Fail fast (5s) instead of hanging when Atlas is unreachable.
    return MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)


def get_db() -> Database:
    return get_client()[get_settings().database_name]
