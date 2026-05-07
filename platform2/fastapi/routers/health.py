"""
GET /health — checks connectivity to all downstream services.
"""

import asyncio
import time

import redis.asyncio as aioredis
from fastapi import APIRouter
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from config import settings
from models.schemas import HealthResponse, ServiceHealth
from services.tb_client import get_tb_client

router = APIRouter(tags=["health"])


async def _check_postgres() -> ServiceHealth:
    try:
        from db.postgres import engine
        t0 = time.monotonic()
        async with engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        return ServiceHealth(status="down", detail=str(exc))


async def _check_redis() -> ServiceHealth:
    try:
        t0 = time.monotonic()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        return ServiceHealth(status="down", detail=str(exc))


async def _check_chroma() -> ServiceHealth:
    try:
        import httpx
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://{settings.chroma_host}:{settings.chroma_port}/api/v1/heartbeat"
            )
            resp.raise_for_status()
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        return ServiceHealth(status="down", detail=str(exc))


async def _check_kafka() -> ServiceHealth:
    try:
        t0 = time.monotonic()
        producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap)
        await asyncio.wait_for(producer.start(), timeout=5)
        await producer.stop()
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        return ServiceHealth(status="down", detail=str(exc))


async def _check_thingsboard() -> ServiceHealth:
    try:
        t0 = time.monotonic()
        ok = await get_tb_client().health_check()
        latency = round((time.monotonic() - t0) * 1000, 1)
        return ServiceHealth(status="ok" if ok else "down", latency_ms=latency)
    except Exception as exc:
        return ServiceHealth(status="down", detail=str(exc))


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    checks = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_chroma(),
        _check_kafka(),
        _check_thingsboard(),
        return_exceptions=False,
    )
    services = {
        "postgres": checks[0],
        "redis": checks[1],
        "chroma": checks[2],
        "kafka": checks[3],
        "thingsboard": checks[4],
    }
    overall = "ok" if all(s.status == "ok" for s in services.values()) else "degraded"
    return HealthResponse(status=overall, services=services)
