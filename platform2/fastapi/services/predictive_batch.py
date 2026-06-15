"""
predictive_batch.py — Daily LSTM predictive maintenance batch job.

Registered in main.py lifespan via APScheduler.
Also callable on-demand via POST /debug/run-predictive.

Job steps:
  1. Query NavNet Registry for all BMS devices
  2. For each device: run LSTM scoring
  3. Write health score to equipment_health TimescaleDB hypertable
  4. If failure_probability > threshold:
       a. Redis dedup (48hr window per device)
       b. Create PREDICTIVE_FAILURE alarm in NavNet Registry
       c. Create work order in PostgreSQL
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

PRED_ALARM_REDIS_TTL = 48 * 3600   # 48 hours — prevents duplicate predictive alarms
BMS_DEVICE_CLASSES   = ["hvac", "energy", "occupancy", "elevator", "fire"]


async def run_predictive_batch() -> dict:
    """
    Main batch entry point. Returns a summary dict with counts.
    Safe to call multiple times concurrently — Redis dedup prevents duplicate alarms.
    """
    t0 = datetime.now(timezone.utc)
    logger.info("predictive_batch: starting at %s", t0.isoformat())

    summary = {
        "started_at": t0.isoformat(),
        "devices_scored": 0,
        "failures_predicted": 0,
        "alarms_created": 0,
        "work_orders_created": 0,
        "errors": 0,
    }

    from services.registry_client import get_registry_client
    from services.predictive import get_predictive_service

    tb  = get_registry_client()
    svc = get_predictive_service()

    # 1. Get all BMS devices
    devices = await _fetch_bms_devices(tb)
    logger.info("predictive_batch: %d BMS devices to score", len(devices))

    # 2. Score each device — run concurrently in batches of 10
    sem = asyncio.Semaphore(10)

    async def _process(device: dict) -> None:
        async with sem:
            await _score_device(device, tb, svc, summary)

    await asyncio.gather(*[_process(d) for d in devices], return_exceptions=True)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    summary["elapsed_seconds"] = round(elapsed, 1)
    logger.info(
        "predictive_batch: complete in %.1fs — scored=%d failures=%d alarms=%d wo=%d errors=%d",
        elapsed,
        summary["devices_scored"],
        summary["failures_predicted"],
        summary["alarms_created"],
        summary["work_orders_created"],
        summary["errors"],
    )
    return summary


# ── Device fetching ───────────────────────────────────────────────────────────

async def _fetch_bms_devices(tb) -> list[dict]:
    """
    Return all devices whose device_class is in BMS_DEVICE_CLASSES.
    Uses TB device listing + attribute check (same approach as train_anomaly.py).
    """
    try:
        # Registry REST: GET /api/tenant/devices  (paged)
        import httpx
        base = settings.registry_url.rstrip("/")
        token = tb._token or (await tb._ensure_token())

        devices: list[dict] = []
        page, page_size = 0, 100

        while True:
            resp = await tb._request(
                "GET",
                "/api/tenant/devices",
                params={"pageSize": page_size, "page": page},
            )
            if not resp:
                break
            batch = resp.get("data", [])
            for device in batch:
                did   = device["id"]["id"]
                attrs = await tb.get_device_attributes(did)
                dc    = attrs.get("device_class", "")
                if dc in BMS_DEVICE_CLASSES:
                    device["_device_class"] = dc
                    device["_attrs"] = attrs
                    devices.append(device)
            if not resp.get("hasNext"):
                break
            page += 1

        return devices

    except Exception as exc:
        logger.error("predictive_batch: failed to fetch devices: %s", exc)
        return []


# ── Per-device scoring ────────────────────────────────────────────────────────

async def _score_device(device: dict, tb, svc, summary: dict) -> None:
    entity_id    = device["id"]["id"]
    device_name  = device.get("name", entity_id)
    device_class = device.get("_device_class", "hvac")

    try:
        result = await svc.score_device(entity_id, device_class)
        if result is None:
            return   # no model or insufficient data

        summary["devices_scored"] += 1

        # 3. Write to equipment_health TimescaleDB
        await _write_health_score(result)

        # 4. Check threshold
        if result.failure_probability < settings.lstm_failure_threshold:
            return

        summary["failures_predicted"] += 1
        logger.info(
            "PREDICTIVE: %s (%s) failure_prob=%.2f window=%s",
            device_name, device_class, result.failure_probability, result.predicted_failure_window,
        )

        # 4a. Redis 48-hour dedup
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            dedup_key = f"pred_alarm:{entity_id}"
            already_alerted = await redis.exists(dedup_key)
            if already_alerted:
                logger.debug("predictive_batch: dedup skip for %s", entity_id)
                return
            # Reserve slot immediately to prevent race condition
            await redis.set(dedup_key, "1", ex=PRED_ALARM_REDIS_TTL)
        finally:
            await redis.aclose()

        # 4b. Create PREDICTIVE_FAILURE alarm in NavNet Registry
        try:
            alarm_id = await tb.create_alarm(
                entity_id=entity_id,
                alarm_type="PREDICTIVE_FAILURE",
                severity="WARNING",
                details={
                    "failure_probability": result.failure_probability,
                    "predicted_failure_window": result.predicted_failure_window,
                    "contributing_features": result.contributing_features,
                    "confidence": result.confidence,
                    "model": "LSTM",
                    "scored_at": result.scored_at.isoformat(),
                },
            )
            # Also write as server attributes for easy widget access
            await tb.set_device_server_attributes(entity_id, {
                "lstm_failure_probability": result.failure_probability,
                "lstm_predicted_window": result.predicted_failure_window,
                "lstm_scored_at": result.scored_at.isoformat(),
            })
            summary["alarms_created"] += 1
            logger.info("Created PREDICTIVE_FAILURE alarm %s for %s", alarm_id, device_name)
        except Exception as exc:
            logger.warning("Failed to create predictive alarm for %s: %s", entity_id, exc)

        # 4c. Create work order in PostgreSQL
        try:
            wo_data = svc.generate_work_order_data(entity_id, result)
            wo_id   = await _create_work_order(entity_id, device_name, device_class, wo_data)
            if wo_id:
                summary["work_orders_created"] += 1
                logger.info("Created predictive work order %s for %s", wo_id, device_name)
        except Exception as exc:
            logger.warning("Failed to create predictive work order for %s: %s", entity_id, exc)

    except Exception as exc:
        logger.exception("predictive_batch: error scoring %s: %s", entity_id, exc)
        summary["errors"] += 1


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _write_health_score(result) -> None:
    from db.postgres import AsyncSessionLocal, EquipmentHealth
    async with AsyncSessionLocal() as session:
        row = EquipmentHealth(
            entity_id=result.entity_id,
            scored_at=result.scored_at,
            health_score=round(1.0 - result.failure_probability, 4),
            failure_probability=result.failure_probability,
            features=result.contributing_features,
            model_version="lstm_v1",
        )
        session.add(row)
        await session.commit()


async def _create_work_order(
    entity_id: str,
    device_name: str,
    device_class: str,
    wo_data: dict,
) -> str | None:
    from db.postgres import AsyncSessionLocal, AuditLog, WorkOrder
    try:
        async with AsyncSessionLocal() as session:
            wo = WorkOrder(
                id=uuid.uuid4(),
                entity_id=entity_id,
                device_name=device_name,
                device_class=device_class,
                fault_description=wo_data["fault_description"],
                recommended_steps=wo_data.get("steps", []),
                parts_required={"parts": wo_data.get("parts", [])},
                estimated_labour_hours=wo_data.get("labour_hours"),
                priority=wo_data.get("priority", 2),
                status="open",
                created_at=datetime.now(timezone.utc),
                # Due by: end of predicted failure window
                due_by=_due_by_from_window(wo_data.get("predicted_window", "72hr")),
            )
            session.add(wo)

            log = AuditLog(
                id=uuid.uuid4(),
                entity_id=entity_id,
                event_type="predictive_work_order_created",
                payload={
                    "work_order_id": str(wo.id),
                    "failure_probability": wo_data.get("failure_probability"),
                    "predicted_window": wo_data.get("predicted_window"),
                },
                created_at=datetime.now(timezone.utc),
            )
            session.add(log)
            await session.commit()
            return str(wo.id)
    except Exception as exc:
        logger.error("Failed to persist predictive work order: %s", exc)
        return None


def _due_by_from_window(window: str) -> datetime:
    hours = {"24hr": 24, "48hr": 48, "72hr": 72}.get(window, 72)
    return datetime.now(timezone.utc) + timedelta(hours=hours)
