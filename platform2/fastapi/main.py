"""
NavNet — FastAPI AI Services
main.py — application entry point with lifespan management.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings

# ── Structured logging setup ──────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logging.basicConfig(level=logging.INFO)
log = structlog.get_logger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: connect to all downstream services and start background workers.
    Shutdown: gracefully close connections and stop consumers.
    """
    log.info("startup", service="navnet-fastapi")

    # 1. Database
    from db.postgres import engine, Base
    async with engine.begin() as conn:
        # Tables already created by Alembic; this is a no-op if schema exists
        pass
    log.info("postgres.connected")

    # 2. Redis
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await app.state.redis.ping()
    log.info("redis.connected")

    # 3. ChromaDB
    try:
        import chromadb
        app.state.chroma = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        app.state.chroma.heartbeat()
        log.info("chroma.connected")
    except Exception as exc:
        log.warning("chroma.unavailable", error=str(exc))
        app.state.chroma = None

    # 4. Kafka consumer (background task)
    from consumers.telemetry import TelemetryConsumer
    consumer = TelemetryConsumer()
    consumer_task = asyncio.create_task(consumer.run(), name="telemetry-consumer")
    app.state.kafka_consumer = consumer
    app.state.kafka_task = consumer_task
    log.info("kafka.consumer.started")

    # 5. APScheduler (predictive batch + topology rebuild)
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from services.predictive_batch import run_predictive_batch

        async def _rebuild_topology() -> None:
            from services.topology import get_topology
            topo = get_topology()
            await topo.async_build()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_predictive_batch,
            trigger="cron",
            hour=settings.lstm_batch_hour,
            minute=0,
            id="predictive_batch",
            replace_existing=True,
        )
        scheduler.add_job(
            _rebuild_topology,
            trigger="cron",
            hour=2,
            minute=0,
            id="topology_rebuild",
            replace_existing=True,
        )
        scheduler.start()
        app.state.scheduler = scheduler
        log.info("scheduler.started", batch_hour=settings.lstm_batch_hour, topology_rebuild_hour=2)
    except Exception as exc:
        log.warning("scheduler.unavailable", error=str(exc))
        app.state.scheduler = None

    # 6. Load topology graph from disk (non-blocking — fire and forget)
    try:
        from services.topology import get_topology
        get_topology().load()
        log.info("topology.loaded")
    except Exception as exc:
        log.warning("topology.load_failed", error=str(exc))

    yield  # ── application runs ──

    # Shutdown
    log.info("shutdown.starting")

    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=False)

    consumer.stop()
    try:
        await asyncio.wait_for(consumer_task, timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        consumer_task.cancel()

    await app.state.redis.aclose()

    from services.registry_client import get_registry_client
    await get_registry_client().close()

    from db.postgres import engine as db_engine
    await db_engine.dispose()

    log.info("shutdown.complete")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="NavNet — AI Services",
    version="1.0.0",
    description="NavNet IoT Operations Intelligence Platform — AI backend services.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — restrict per customer in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    from datetime import datetime
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "detail": str(exc),
            "ts": datetime.utcnow().isoformat(),
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────

from routers.health import router as health_router
from routers.webhook import router as webhook_router
from routers.workorders import router as workorders_router

app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(workorders_router)

# chat router registered here; implementation in Phase 3
try:
    from routers.chat import router as chat_router
    app.include_router(chat_router)
except ImportError:
    pass


# ── Debug endpoints (remove / gate behind auth in production) ─────────────────

@app.post("/debug/run-predictive", tags=["debug"])
async def debug_run_predictive() -> dict:
    """Force-trigger the LSTM predictive batch job."""
    from services.predictive_batch import run_predictive_batch
    asyncio.create_task(run_predictive_batch())
    return {"status": "triggered"}


@app.post("/debug/rebuild-topology", tags=["debug"])
async def debug_rebuild_topology() -> dict:
    """Force-rebuild the device topology graph."""
    from services.topology import get_topology
    topo = get_topology()
    await topo.async_build()
    return {"status": "rebuilt", "stats": topo.stats()}


@app.post("/debug/train-gnn", tags=["debug"])
async def debug_train_gnn(lookback_days: int = 30, epochs: int = 50) -> dict:
    """Train the GNN root cause model from audit log cascade entries."""
    from services.gnn import get_gnn_service
    result = await get_gnn_service().train_from_audit_log(
        lookback_days=lookback_days, epochs=epochs
    )
    return result
