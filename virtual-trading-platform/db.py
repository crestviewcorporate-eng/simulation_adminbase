import asyncio
import logging
import os
from typing import Optional
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import pymongo

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "virtual_trading_platform")

client: Optional[AsyncIOMotorClient] = None
db: Optional[AsyncIOMotorDatabase] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None


def get_client() -> AsyncIOMotorClient:
    global client, db, _client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if client is None or _client_loop is None or _client_loop != current_loop or _client_loop.is_closed():
        client = AsyncIOMotorClient(MONGO_URI)
        _client_loop = current_loop
        db = client[MONGO_DB_NAME]
    return client


def get_db() -> AsyncIOMotorDatabase:
    """Dependency / helper to get async database handle."""
    global db
    get_client()
    return db


async def close_db_connection():
    global client, db, _client_loop
    if client is not None:
        client.close()
        client = None
        db = None
        _client_loop = None
        logger.info("MongoDB connection closed.")


async def init_db():
    """Create collections and required indexes on application startup."""
    database = get_db()
    logger.info("Initializing MongoDB indexes...")

    try:
        # 1. users: unique index on user_id
        await database.users.create_index("user_id", unique=True)
        logger.info("Created unique index on 'users.user_id'")

        # 2. trades collections: compound index on {user_id, status}
        trade_collections = ["trades_option", "trades_future", "trades_cash"]
        for coll_name in trade_collections:
            await database[coll_name].create_index(
                [("user_id", pymongo.ASCENDING), ("status", pymongo.ASCENDING)]
            )
            logger.info(f"Created compound index on '{coll_name}' for (user_id, status)")

        # 3. admins collection: unique index on username
        await database.admins.create_index("username", unique=True)

        # 4. instruments lookup indexes
        await database.instruments.create_index(
            [
                ("symbol", 1),
                ("segment", 1),
                ("expiry", 1),
                ("strike", 1),
                ("option_type", 1),
            ]
        )
        await database.instruments.create_index("tradingsymbol")

        logger.info("MongoDB indexes successfully initialized.")
    except Exception as e:
        logger.warning(
            f"Could not initialize MongoDB indexes (MongoDB may be offline or unreachable at {MONGO_URI}): {e}"
        )
