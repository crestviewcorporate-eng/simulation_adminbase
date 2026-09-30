from scrip_master import scrip_master
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import init_db, close_db_connection
from mtm_engine import start_mtm_engine
from order_engine import start_order_engine
from settlement_engine import start_settlement_engine, run_settlement_cycle
from routers.admin_routes import router as admin_router
from routers.user_routes import router as user_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("virtual_trading_platform")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # App startup: Initialize DB, create indexes, and start MTM, Order, and Settlement background engines
    logger.info("Starting Virtual Trading Platform application...")
    await init_db()
    logger.info("Ensuring Scrip Master instruments are indexed...")
    await asyncio.to_thread(scrip_master.ensure_loaded)
    logger.info(f"Scrip master loaded successfully: {len(scrip_master._instruments)} instruments indexed.")

    # Startup catch-up: Settle any contracts that expired while the server was down
    try:
        startup_settle_res = await run_settlement_cycle()
        logger.info(f"Startup settlement catch-up complete: {startup_settle_res}")
    except Exception as e:
        logger.error(f"Error during startup settlement catch-up: {e}")

    mtm_task = asyncio.create_task(start_mtm_engine(interval_seconds=5.0))
    order_task = asyncio.create_task(start_order_engine(interval_seconds=3.0))
    settlement_task = asyncio.create_task(start_settlement_engine(interval_seconds=60.0))
    logger.info("MTM, Order, and Settlement background engine tasks created.")

    yield

    # App shutdown: Clean up background tasks and DB connections
    logger.info("Shutting down Virtual Trading Platform application...")
    for task in (mtm_task, order_task, settlement_task):
        task.cancel()
    for task in (mtm_task, order_task, settlement_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error during background task cancellation: {e}")

    await close_db_connection()


app = FastAPI(
    title="Virtual Trading Platform API",
    description="Virtual/Paper Trading System (Admin + User roles, Options/Futures/Cash on NIFTY/BANKNIFTY/SENSEX)",
    version="0.1.0",
    lifespan=lifespan,
)

# Robust CORS middleware supporting all local and remote origins
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers with and without /api prefix for maximum flexibility
app.include_router(admin_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(admin_router)
app.include_router(user_router)


@app.get("/")
@app.get("/api")
async def root():
    return {
        "name": "Virtual Trading Platform API",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health")
@app.get("/api/health")
async def health():
    return {"status": "ok"}
