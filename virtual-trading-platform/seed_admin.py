"""Seed Admin Script
Standalone CLI script to seed an initial administrator into the MongoDB 'admins' collection.

Usage:
  python seed_admin.py
  python seed_admin.py --username superadmin --password MySecurePass123
"""
import argparse
import asyncio
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

from auth import hash_password
from db import close_db_connection, get_db

load_dotenv()


async def seed_admin(username: str, password: str):
    database = get_db()
    admins_coll = database["admins"]

    # Ensure unique index on username in admins collection
    try:
        await admins_coll.create_index("username", unique=True)
    except Exception as e:
        print(f"[WARN] Index creation notice: {e}")

    # Check if admin already exists
    existing_admin = await admins_coll.find_one({"username": username})

    if existing_admin:
        print(f"\n[INFO] Admin user '{username}' already exists in database. No changes made.")
        return False

    # Hash password and insert
    hashed = hash_password(password)
    admin_doc = {
        "username": username,
        "password_hash": hashed,
        "role": "admin",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await admins_coll.insert_one(admin_doc)
    print(f"\n[SUCCESS] Admin user '{username}' successfully created!")
    print(f"          Document ID: {result.inserted_id}")
    print(f"          Role: admin\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Seed Admin user into MongoDB")
    parser.add_argument(
        "--username",
        type=str,
        default=os.getenv("ADMIN_USERNAME", "admin"),
        help="Admin username (default from ADMIN_USERNAME env or 'admin')",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("ADMIN_PASSWORD", "admin123"),
        help="Admin password (default from ADMIN_PASSWORD env or 'admin123')",
    )

    args = parser.parse_args()

    async def run():
        try:
            await seed_admin(args.username, args.password)
        finally:
            await close_db_connection()

    asyncio.run(run())


if __name__ == "__main__":
    main()
