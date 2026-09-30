"""Migration: Add allowed_instrument_types to existing user documents.
Defaults all existing users to allowed_instrument_types = ["INDEX"].
"""
import asyncio
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient

from dotenv import load_dotenv
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME") or os.getenv("DB_NAME") or "virtual_trading_platform"


async def run_migration():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    print(f"Connected to DB [{DB_NAME}]. Running migration...")

    result = await db.users.update_many(
        {"allowed_instrument_types": {"$exists": False}},
        {"$set": {"allowed_instrument_types": ["INDEX"]}}
    )
    print(f"Updated {result.modified_count} users with allowed_instrument_types=['INDEX'].")
    client.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
