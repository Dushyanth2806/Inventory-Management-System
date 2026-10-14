"""Read-only MongoDB discovery: lists databases, collections, and field names. Never prints secrets or values."""
import os
from collections import Counter

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()
uri = os.getenv("MONGODB_URI")
if not uri:
    raise SystemExit("MONGODB_URI is not set")

try:
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    print("Connection: OK")
    for db_name in client.list_database_names():
        if db_name in ("admin", "local", "config"):
            continue
        db = client[db_name]
        for coll in db.list_collection_names():
            c = db[coll]
            count = c.estimated_document_count()
            fields, types = Counter(), {}
            for doc in c.find().limit(20):
                for k, v in doc.items():
                    fields[k] += 1
                    types.setdefault(k, type(v).__name__)
            print(f"\n{db_name}.{coll}  (~{count} docs)")
            for k, n in fields.items():
                print(f"   {k}: {types[k]} (in {n}/20 sampled)")
except PyMongoError as e:
    print("Connection/query FAILED:", type(e).__name__, str(e).split(",")[0][:200])
