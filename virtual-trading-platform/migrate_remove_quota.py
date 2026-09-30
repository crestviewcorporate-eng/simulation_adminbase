import asyncio
import logging
import sys
from datetime import datetime, timezone
from db import get_db, close_db_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_remove_quota")

# ANSI Color codes for terminal highlighting
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def run_migration():
    db = get_db()
    print(f"\n{BOLD}======================================================{RESET}")
    print(f"{BOLD}  ONE-TIME MIGRATION: REMOVE TRADE QUOTA & BACKFILL MARGINS  {RESET}")
    print(f"{BOLD}======================================================{RESET}\n")

    # -----------------------------------------------------------------------
    # Step 1: Unset trade_limit and trades_used on all users in db.users
    # -----------------------------------------------------------------------
    print(f"{YELLOW}>>> Step 1: Removing 'trade_limit' and 'trades_used' from all user documents...{RESET}")
    users_cursor = db.users.find({})
    total_users_count = await db.users.count_documents({})
    
    unset_result = await db.users.update_many(
        {},
        {"$unset": {"trade_limit": "", "trades_used": ""}}
    )
    users_unset_count = unset_result.modified_count
    print(f"{GREEN}✓ Successfully unset quota fields for {users_unset_count}/{total_users_count} users.{RESET}\n")

    # -----------------------------------------------------------------------
    # Step 2: Backfill margin_blocked_amount on OPEN option and cash trades
    # -----------------------------------------------------------------------
    print(f"{YELLOW}>>> Step 2: Scanning open Option and Cash trades for margin backfilling...{RESET}")
    backfilled_trades_count = 0
    total_margin_locked = 0.0
    affected_user_ids = set()

    for seg in ("option", "cash"):
        coll_name = f"trades_{seg}"
        coll = db[coll_name]

        # Find OPEN trades where margin_blocked_amount is missing or 0
        query = {
            "status": "OPEN",
            "$or": [
                {"margin_blocked_amount": {"$exists": False}},
                {"margin_blocked_amount": 0},
                {"margin_blocked_amount": 0.0},
                {"margin_blocked_amount": None},
            ]
        }
        open_trades = await coll.find(query).to_list(length=5000)

        for trade in open_trades:
            trade_id = trade.get("trade_id")
            user_id = trade.get("user_id")
            entry_price = float(trade.get("entry_price", 0.0))
            qty = int(trade.get("qty", 1))

            estimated_lock = round(entry_price * qty, 2)

            # 1. Update trade doc with computed margin_blocked_amount
            await coll.update_one(
                {"trade_id": trade_id},
                {"$set": {"margin_blocked_amount": estimated_lock, "updated_at": datetime.now(timezone.utc)}}
            )

            # 2. Adjust user's balance: available_balance -= estimated_lock, margin_blocked += estimated_lock
            await db.users.update_one(
                {"user_id": user_id},
                {
                    "$inc": {
                        "available_balance": -estimated_lock,
                        "margin_blocked": estimated_lock,
                    },
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )

            backfilled_trades_count += 1
            total_margin_locked += estimated_lock
            affected_user_ids.add(user_id)

            print(
                f"  [{seg.upper():6s}] Trade {BOLD}{trade_id}{RESET} | User: {user_id} | "
                f"Locked: ₹{estimated_lock:,.2f} ({entry_price:.2f} × {qty} qty)"
            )

    if backfilled_trades_count == 0:
        print(f"{GREEN}✓ No unmigrated open Option/Cash trades found. All existing trades already have margin recorded.{RESET}\n")
    else:
        print(f"\n{GREEN}✓ Backfilled {backfilled_trades_count} open trades across {len(affected_user_ids)} users (Total locked: ₹{total_margin_locked:,.2f}).{RESET}\n")

    # -----------------------------------------------------------------------
    # Step 3: Scan for negative available_balance and audit
    # -----------------------------------------------------------------------
    print(f"{YELLOW}>>> Step 3: Checking user accounts for negative available balance...{RESET}")
    all_users = await db.users.find({}).to_list(length=5000)
    negative_balance_users = []

    for u in all_users:
        uid = u.get("user_id")
        bal = float(u.get("balance", 0.0))
        avail = float(u.get("available_balance", 0.0))
        blocked = float(u.get("margin_blocked", 0.0))
        realized = float(u.get("realized_pnl", 0.0))

        if avail < 0:
            negative_balance_users.append({
                "user_id": uid,
                "name": u.get("name", ""),
                "balance": bal,
                "available_balance": avail,
                "margin_blocked": blocked,
                "realized_pnl": realized,
                "shortfall": abs(avail)
            })

    # -----------------------------------------------------------------------
    # Final Migration Summary Report
    # -----------------------------------------------------------------------
    print(f"\n{BOLD}======================================================{RESET}")
    print(f"{BOLD}                 MIGRATION SUMMARY                    {RESET}")
    print(f"{BOLD}======================================================{RESET}")
    print(f"Total Users Checked       : {len(all_users)}")
    print(f"Users Quota Fields Unset  : {users_unset_count}")
    print(f"Open Trades Backfilled    : {backfilled_trades_count}")
    print(f"Total Margin Back-Locked  : ₹{total_margin_locked:,.2f}")

    if negative_balance_users:
        print(f"\n{RED}{BOLD}⚠ ATTENTION REQUIRED: {len(negative_balance_users)} USER(S) WITH NEGATIVE AVAILABLE BALANCE:{RESET}")
        for neg in negative_balance_users:
            print(
                f"{RED}  • User: {BOLD}{neg['user_id']}{RESET}{RED} ({neg['name']}) | "
                f"Balance: ₹{neg['balance']:,.2f} | "
                f"Blocked: ₹{neg['margin_blocked']:,.2f} | "
                f"Available: {BOLD}₹{neg['available_balance']:,.2f}{RESET}{RED} "
                f"(Admin Top-Up Required: ₹{neg['shortfall']:,.2f}){RESET}"
            )
        print(f"{RED}Note: These users had open positions exceeding their allocated capital. Admin should add funds via PUT /admin/users/{{user_id}}/balance/add.{RESET}\n")
    else:
        print(f"\n{GREEN}{BOLD}✓ HEALTH CHECK PASSED: 0 users have negative available balance.{RESET}\n")

    print(f"{BOLD}======================================================{RESET}\n")

    await close_db_connection()


if __name__ == "__main__":
    asyncio.run(run_migration())
