#!/usr/bin/env python
"""MongoDB Export, Import, and Clone Tool for FarmOps AI.

Usage:
    # 1. Export all data from current MongoDB to a local JSON backup file
    python scripts/migrate_mongodb.py --action export --file mongodb_backup.json

    # 2. Import local JSON backup file to your new MongoDB database
    python scripts/migrate_mongodb.py --action import --file mongodb_backup.json --target-uri "mongodb+srv://user:pass@your-cluster.mongodb.net"

    # 3. Direct clone from current MongoDB to your new MongoDB cluster
    python scripts/migrate_mongodb.py --action clone --target-uri "mongodb+srv://user:pass@your-cluster.mongodb.net"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("mongo-migrate")

# Default source URI from current project
DEFAULT_SOURCE_URI = "mongodb+srv://username321:authenpass123@farmops-cluster.smcj9lz.mongodb.net/?appName=farmops-cluster"
DEFAULT_DB_NAME = "farmops"


def get_source_uri() -> str:
    """Read source URI from .env if available, else fallback to default."""
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        return os.getenv("MONGODB_URI", DEFAULT_SOURCE_URI)
    except Exception:
        return DEFAULT_SOURCE_URI


def export_data(source_uri: str, db_name: str, output_file: str) -> None:
    """Export all documents from source MongoDB to a JSON file."""
    log.info("Connecting to source MongoDB: %s", source_uri[:40] + "...")
    client = MongoClient(source_uri, serverSelectionTimeoutMS=10000)
    db = client[db_name]

    collections = db.list_collection_names()
    log.info("Found collections in source database '%s': %s", db_name, collections)

    backup_data: dict[str, list] = {}
    total_docs = 0

    for col_name in collections:
        collection = db[col_name]
        docs = list(collection.find())
        backup_data[col_name] = docs
        count = len(docs)
        total_docs += count
        log.info("Exported %d documents from collection '%s'", count, col_name)

    log.info("Writing total %d documents to '%s'...", total_docs, output_file)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(json_util.dumps(backup_data, indent=2))

    log.info("SUCCESS: Export completed! File saved to %s (%d documents)", output_file, total_docs)


def import_data(target_uri: str, db_name: str, input_file: str) -> None:
    """Import documents from a JSON backup file to target MongoDB."""
    if not Path(input_file).exists():
        log.error("File '%s' not found!", input_file)
        sys.exit(1)

    log.info("Reading backup file: %s", input_file)
    with open(input_file, "r", encoding="utf-8") as f:
        backup_data = json_util.loads(f.read())

    log.info("Connecting to target MongoDB: %s", target_uri[:40] + "...")
    target_client = MongoClient(target_uri, serverSelectionTimeoutMS=10000)
    target_db = target_client[db_name]

    total_inserted = 0
    for col_name, docs in backup_data.items():
        if not docs:
            continue
        col = target_db[col_name]
        # Clear existing or insert batch
        res = col.insert_many(docs, ordered=False)
        inserted_count = len(res.inserted_ids)
        total_inserted += inserted_count
        log.info("Imported %d documents into collection '%s'", inserted_count, col_name)

    log.info("SUCCESS: Import completed! Imported %d total documents into target database '%s'", total_inserted, db_name)


def clone_direct(source_uri: str, target_uri: str, db_name: str) -> None:
    """Directly copy all data from source MongoDB to target MongoDB."""
    log.info("Starting direct clone from source to target...")
    source_client = MongoClient(source_uri, serverSelectionTimeoutMS=10000)
    target_client = MongoClient(target_uri, serverSelectionTimeoutMS=10000)

    src_db = source_client[db_name]
    target_db = target_client[db_name]

    collections = src_db.list_collection_names()
    log.info("Collections to clone: %s", collections)

    for col_name in collections:
        docs = list(src_db[col_name].find())
        if docs:
            target_db[col_name].insert_many(docs, ordered=False)
            log.info("Cloned %d documents for collection '%s'", len(docs), col_name)

    log.info("SUCCESS: Direct clone finished successfully!")


def main() -> None:
    parser = argparse.ArgumentParser(description="MongoDB Clone/Export/Import Utility")
    parser.add_argument(
        "--action",
        choices=["export", "import", "clone"],
        required=True,
        help="Action: export to JSON file, import from JSON file, or direct clone",
    )
    parser.add_argument("--source-uri", default="", help="Source MongoDB URI (defaults to .env MONGODB_URI)")
    parser.add_argument("--target-uri", default="", help="Target MongoDB URI (your new cluster)")
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME, help="Database name (default: farmops)")
    parser.add_argument("--file", default="mongodb_backup.json", help="Backup file path (default: mongodb_backup.json)")

    args = parser.parse_args()

    source_uri = args.source_uri if args.source_uri else get_source_uri()

    if args.action == "export":
        export_data(source_uri, args.db_name, args.file)
    elif args.action == "import":
        if not args.target_uri:
            log.error("Please provide --target-uri for your new MongoDB database!")
            sys.exit(1)
        import_data(args.target_uri, args.db_name, args.file)
    elif args.action == "clone":
        if not args.target_uri:
            log.error("Please provide --target-uri for your new MongoDB database!")
            sys.exit(1)
        clone_direct(source_uri, args.target_uri, args.db_name)


if __name__ == "__main__":
    main()
