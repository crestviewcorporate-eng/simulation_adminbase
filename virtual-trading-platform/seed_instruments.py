"""Seed Instruments Script
DEPRECATION NOTICE:
  - The FUTURE and OPTION entries in this file are DEPRECATED early testing placeholders.
  - The live source of truth for all Future and Option contracts is  which
    downloads and indexes real AngelOne tokens and running expiries daily.
  - The CASH SPOT entries (e.g., NIFTY 99926000, BANKNIFTY 99926009, SENSEX 99919000)
    remain active static spot tokens for underlying index quotes.
"""
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

from db import close_db_connection, get_db

load_dotenv()

SAMPLE_INSTRUMENTS = [
    # -----------------------------------------------------------------------
    # NIFTY
    # -----------------------------------------------------------------------
    {
        "symbol": "NIFTY",
        "name": "NIFTY 50 SPOT",
        "exchange": "NSE",
        "segment": "cash",
        "tradingsymbol": "Nifty 50",
        "symboltoken": "99926000",
        "lot_size": 1,
        "tick_size": 0.05,
    },
    {
        "symbol": "NIFTY",
        "name": "NIFTY 50 FUT",
        "exchange": "NFO",
        "segment": "future",
        "tradingsymbol": "NIFTY26MARFUT",
        "symboltoken": "10001",
        "expiry": "28MAR2026",
        "lot_size": 25,
        "tick_size": 0.05,
    },
    {
        "symbol": "NIFTY",
        "name": "NIFTY 50 OPT CE",
        "exchange": "NFO",
        "segment": "option",
        "tradingsymbol": "NIFTY26MAR22500CE",
        "symboltoken": "10002",
        "expiry": "28MAR2026",
        "strike": 22500.0,
        "option_type": "CE",
        "lot_size": 25,
        "tick_size": 0.05,
    },
    {
        "symbol": "NIFTY",
        "name": "NIFTY 50 OPT PE",
        "exchange": "NFO",
        "segment": "option",
        "tradingsymbol": "NIFTY26MAR22500PE",
        "symboltoken": "10003",
        "expiry": "28MAR2026",
        "strike": 22500.0,
        "option_type": "PE",
        "lot_size": 25,
        "tick_size": 0.05,
    },

    # -----------------------------------------------------------------------
    # BANKNIFTY
    # -----------------------------------------------------------------------
    {
        "symbol": "BANKNIFTY",
        "name": "NIFTY BANK SPOT",
        "exchange": "NSE",
        "segment": "cash",
        "tradingsymbol": "Nifty Bank",
        "symboltoken": "99926009",
        "lot_size": 1,
        "tick_size": 0.05,
    },
    {
        "symbol": "BANKNIFTY",
        "name": "NIFTY BANK FUT",
        "exchange": "NFO",
        "segment": "future",
        "tradingsymbol": "BANKNIFTY26MARFUT",
        "symboltoken": "20001",
        "expiry": "28MAR2026",
        "lot_size": 15,
        "tick_size": 0.05,
    },
    {
        "symbol": "BANKNIFTY",
        "name": "NIFTY BANK OPT CE",
        "exchange": "NFO",
        "segment": "option",
        "tradingsymbol": "BANKNIFTY26MAR48000CE",
        "symboltoken": "20002",
        "expiry": "28MAR2026",
        "strike": 48000.0,
        "option_type": "CE",
        "lot_size": 15,
        "tick_size": 0.05,
    },
    {
        "symbol": "BANKNIFTY",
        "name": "NIFTY BANK OPT PE",
        "exchange": "NFO",
        "segment": "option",
        "tradingsymbol": "BANKNIFTY26MAR48000PE",
        "symboltoken": "20003",
        "expiry": "28MAR2026",
        "strike": 48000.0,
        "option_type": "PE",
        "lot_size": 15,
        "tick_size": 0.05,
    },

    # -----------------------------------------------------------------------
    # SENSEX
    # -----------------------------------------------------------------------
    {
        "symbol": "SENSEX",
        "name": "BSE SENSEX SPOT",
        "exchange": "BSE",
        "segment": "cash",
        "tradingsymbol": "SENSEX",
        "symboltoken": "99919000",
        "lot_size": 1,
        "tick_size": 0.05,
    },
    {
        "symbol": "SENSEX",
        "name": "BSE SENSEX FUT",
        "exchange": "BFO",
        "segment": "future",
        "tradingsymbol": "SENSEX26MARFUT",
        "symboltoken": "30001",
        "expiry": "28MAR2026",
        "lot_size": 10,
        "tick_size": 0.05,
    },
    {
        "symbol": "SENSEX",
        "name": "BSE SENSEX OPT CE",
        "exchange": "BFO",
        "segment": "option",
        "tradingsymbol": "SENSEX26MAR74000CE",
        "symboltoken": "30002",
        "expiry": "28MAR2026",
        "strike": 74000.0,
        "option_type": "CE",
        "lot_size": 10,
        "tick_size": 0.05,
    },
    {
        "symbol": "SENSEX",
        "name": "BSE SENSEX OPT PE",
        "exchange": "BFO",
        "segment": "option",
        "tradingsymbol": "SENSEX26MAR74000PE",
        "symboltoken": "30003",
        "expiry": "28MAR2026",
        "strike": 74000.0,
        "option_type": "PE",
        "lot_size": 10,
        "tick_size": 0.05,
    },
]


async def seed_instruments():
    database = get_db()
    instruments_coll = database["instruments"]

    await instruments_coll.create_index(
        [
            ("symbol", 1),
            ("segment", 1),
            ("expiry", 1),
            ("strike", 1),
            ("option_type", 1),
        ]
    )
    await instruments_coll.create_index("tradingsymbol")

    upsert_count = 0
    for item in SAMPLE_INSTRUMENTS:
        item["updated_at"] = datetime.now(timezone.utc)
        query = {
            "symbol": item["symbol"],
            "segment": item["segment"],
            "tradingsymbol": item["tradingsymbol"],
        }
        await instruments_coll.update_one(query, {"$set": item}, upsert=True)
        upsert_count += 1

    print(f"\n[SUCCESS] Seeded/Updated {upsert_count} instruments in MongoDB Atlas.")


def main():
    async def run():
        try:
            await seed_instruments()
        finally:
            await close_db_connection()

    asyncio.run(run())


if __name__ == "__main__":
    main()
