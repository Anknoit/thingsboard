"""
Webhook receivers from NavNet Registry rule chains.

POST /webhook/alarm   — single alarm created
POST /webhook/cascade — potential cascade (3+ alarms in 60s window)

Both return 200 immediately; AI enrichment runs in background.
"""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from config import settings
from models.schemas import AlarmWebhookPayload, CascadeWebhookPayload, WebhookAck
from services.registry_client import RegistryClient, get_registry_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# ── In-process cascade accumulator ───────────────────────────────────────────
# Tracks (alarm_id, entity_id, ts) for alarms received in the last window.
# Keyed by a rolling bucket; entries older than CASCADE_WINDOW_SECONDS are pruned.
_cascade_buffer: list[dict] = []
_cascade_lock = asyncio.Lock()


async def _get_redis() -> aioredis.Redis:
    """Return a short-lived Redis connection."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


# ── Background: enrich alarm with anomaly score ──────────────────────────────

async def _enrich_alarm_bg(payload: AlarmWebhookPayload, tb: RegistryClient) -> None:
    """
    Background task: score the alarm with the anomaly service and write
    AI attributes back to the device in NavNet Registry.
    Runs after 200 is already returned to the caller.
    """
    try:
        # Import lazily to avoid circular deps at startup
        from services.anomaly import get_anomaly_service

        # Fetch latest telemetry for scoring
        latest = await tb.get_latest_telemetry(payload.entity_id)
        attrs = await tb.get_device_attributes(payload.entity_id)
        device_class = attrs.get("device_class", "unknown")

        service = get_anomaly_service()
        result = await asyncio.get_event_loop().run_in_executor(
            None, service.score, payload.entity_id, device_class, latest
        )

        enrichment = {
            "ai_anomaly_score": result.score,
            "ai_sigma": result.sigma,
            "ai_explanation": result.explanation,
            "ai_scored_at": result.scored_at.isoformat(),
        }
        await tb.set_device_server_attributes(payload.entity_id, enrichment)
        logger.info(
            "Alarm %s enriched: score=%.1f sigma=%.2f anomaly=%s",
            payload.alarm_id,
            result.score,
            result.sigma,
            result.is_anomaly,
        )
    except Exception:
        logger.exception("Failed to enrich alarm %s", payload.alarm_id)


# ── Background: GNN cascade root-cause analysis ───────────────────────────────

async def _analyze_cascade_bg(alarm_entries: list[dict], tb: RegistryClient) -> None:
    """
    Background task: run GNN root-cause analysis and write results back to
    all cascade alarms in NavNet Registry.
    """
    try:
        from services.anomaly import get_anomaly_service
        from services.gnn import get_gnn_service

        entity_ids = [e["entity_id"] for e in alarm_entries]
        alarm_ids  = [e["alarm_id"]  for e in alarm_entries]

        # Collect anomaly scores + alarm counts to feed the GNN
        anomaly_scores: dict[str, float] = {}
        alarm_counts:   dict[str, int]   = {}
        anomaly_svc = get_anomaly_service()
        for entry in alarm_entries:
            eid = entry["entity_id"]
            try:
                attrs = await tb.get_device_attributes(eid)
                dc    = attrs.get("device_class", "")
                score = float(attrs.get("ai_anomaly_score", 0.0))
                anomaly_scores[eid] = score
                # Count alarms for this device in the current cascade window
                alarm_counts[eid] = alarm_counts.get(eid, 0) + 1
            except Exception:
                pass

        t0 = time.monotonic()
        service = get_gnn_service()
        result = await asyncio.get_event_loop().run_in_executor(
            None, service.find_root_cause, entity_ids, anomaly_scores, alarm_counts
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        result.duration_ms = duration_ms

        enrichment = {
            "root_cause_entity_id": result.root_cause_entity_id,
            "root_cause_device_name": result.root_cause_device_name,
            "cascade_explanation": result.explanation,
            "gnn_confidence": result.confidence,
            "blast_radius_count": len(result.blast_radius),
        }

        # Write to all cascade alarms
        for alarm_id in alarm_ids:
            try:
                await tb.update_alarm_attributes(alarm_id, enrichment)
            except Exception:
                logger.warning("Could not update alarm %s", alarm_id)

        logger.info(
            "Cascade resolved in %dms: root=%s confidence=%.2f blast=%d",
            duration_ms,
            result.root_cause_device_name,
            result.confidence,
            len(result.blast_radius),
        )

        # Audit log — event type 'alarm_cascade_analyzed' is used for GNN training
        from db.postgres import AsyncSessionLocal, AuditLog
        import uuid
        async with AsyncSessionLocal() as session:
            log = AuditLog(
                id=uuid.uuid4(),
                entity_id=result.root_cause_entity_id,
                event_type="alarm_cascade_analyzed",
                payload={
                    "alarm_ids": alarm_ids,
                    "entity_ids": entity_ids,
                    "root_cause_entity_id": result.root_cause_entity_id,
                    "anomaly_scores": anomaly_scores,
                    "alarm_counts": alarm_counts,
                    "confidence": result.confidence,
                    "duration_ms": duration_ms,
                },
            )
            session.add(log)
            await session.commit()

    except Exception:
        logger.exception("Cascade analysis failed for %d alarms", len(alarm_entries))


# ── Prune old cascade buffer entries ─────────────────────────────────────────

async def _maybe_trigger_cascade(new_entry: dict, tb: RegistryClient, tasks: BackgroundTasks) -> None:
    """Add alarm to cascade buffer; fire GNN analysis if threshold met."""
    now = time.time()
    window = settings.cascade_window_seconds
    threshold = settings.cascade_alarm_count

    async with _cascade_lock:
        _cascade_buffer.append({**new_entry, "_added": now})
        # Prune entries outside the window
        cutoff = now - window
        recent = [e for e in _cascade_buffer if e["_added"] >= cutoff]
        _cascade_buffer.clear()
        _cascade_buffer.extend(recent)

        if len(recent) >= threshold:
            # Snapshot and clear to avoid double-triggering
            snapshot = list(recent)
            _cascade_buffer.clear()

    if len(recent) >= threshold:
        logger.warning(
            "Cascade detected: %d alarms in %ds window — triggering GNN",
            len(snapshot),
            window,
        )
        tasks.add_task(_analyze_cascade_bg, snapshot, tb)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/webhook/alarm", response_model=WebhookAck, status_code=200)
async def alarm_webhook(
    payload: AlarmWebhookPayload,
    background_tasks: BackgroundTasks,
    tb: RegistryClient = Depends(get_registry_client),
) -> WebhookAck:
    """
    Receives NavNet Registry alarm events. Returns 200 immediately.
    Background: scores anomaly and writes ai_* attributes back to device.
    """
    redis = await _get_redis()
    dedup_key = f"alarm:{payload.alarm_id}"

    try:
        # Redis SET NX with 60s TTL — skip if already processed
        acquired = await redis.set(dedup_key, "1", ex=60, nx=True)
        if not acquired:
            logger.debug("Alarm %s already processed — skipping", payload.alarm_id)
            return WebhookAck(status="duplicate", alarm_id=payload.alarm_id)

        # Store active alarm reference for Kafka consumer dedup
        await redis.set(
            f"active_alarm:{payload.entity_id}",
            payload.alarm_id,
            ex=settings.cascade_window_seconds * 5,
        )

        background_tasks.add_task(_enrich_alarm_bg, payload, tb)

        # Feed cascade accumulator
        entry = {
            "alarm_id": payload.alarm_id,
            "entity_id": payload.entity_id,
            "entity_name": payload.entity_name,
            "alarm_type": payload.alarm_type,
        }
        await _maybe_trigger_cascade(entry, tb, background_tasks)

        logger.info(
            "Alarm webhook received: alarm=%s entity=%s type=%s severity=%s",
            payload.alarm_id,
            payload.entity_name,
            payload.alarm_type,
            payload.severity,
        )
        return WebhookAck(status="accepted", alarm_id=payload.alarm_id)
    finally:
        await redis.aclose()


@router.post("/webhook/cascade", response_model=WebhookAck, status_code=200)
async def cascade_webhook(
    payload: CascadeWebhookPayload,
    background_tasks: BackgroundTasks,
    tb: RegistryClient = Depends(get_registry_client),
) -> WebhookAck:
    """
    Explicit cascade signal from NavNet Registry rule chain counter node.
    Also feeds individual alarm into cascade accumulator.
    """
    entry = {
        "alarm_id": payload.alarm_id,
        "entity_id": payload.entity_id,
        "entity_name": payload.entity_name,
        "alarm_type": payload.alarm_type,
    }
    await _maybe_trigger_cascade(entry, tb, background_tasks)

    logger.info(
        "Cascade webhook received: entity=%s alarm=%s",
        payload.entity_name,
        payload.alarm_id,
    )
    return WebhookAck(status="accepted", alarm_id=payload.alarm_id)
