"""
context_builder.py — Assembles full device context for LLM prompt injection.

Fetches: device metadata, latest telemetry, 48hr trend summary,
         recent alarms, shared attributes.
Results are cached in Redis for 30 seconds to avoid hammering ThingsBoard
when multiple chat turns happen in quick succession.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone

import redis.asyncio as aioredis

from config import settings
from services.tb_client import TBClient, TBClientError, get_tb_client

logger = logging.getLogger(__name__)

CACHE_TTL = 30  # seconds


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _summarise_timeseries(readings: list[dict]) -> dict[str, dict]:
    """
    Pivot [{ts, values: {key: value}}] into per-key stats:
    { key: { min, max, mean, latest, trend } }
    where trend is "rising" | "falling" | "stable".
    """
    per_key: dict[str, list[float]] = {}
    for point in readings:
        for key, raw in point.get("values", {}).items():
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            per_key.setdefault(key, []).append(val)

    summary: dict[str, dict] = {}
    for key, values in per_key.items():
        if not values:
            continue
        mn, mx, mean = min(values), max(values), statistics.mean(values)

        # Simple linear trend on last 10 points
        recent = values[-10:]
        if len(recent) >= 3:
            first_half = statistics.mean(recent[: len(recent) // 2])
            second_half = statistics.mean(recent[len(recent) // 2 :])
            delta = second_half - first_half
            if abs(delta) < 0.01 * (mx - mn + 1e-9):
                trend = "stable"
            elif delta > 0:
                trend = "rising"
            else:
                trend = "falling"
        else:
            trend = "stable"

        summary[key] = {
            "min": round(mn, 3),
            "max": round(mx, 3),
            "mean": round(mean, 3),
            "latest": round(values[-1], 3),
            "trend": trend,
            "samples": len(values),
        }
    return summary


def _format_alarms(alarms: list[dict]) -> list[dict]:
    """Extract relevant fields from TB alarm objects."""
    out = []
    for alarm in alarms:
        out.append({
            "type": alarm.get("type", "unknown"),
            "severity": alarm.get("severity", "unknown"),
            "status": alarm.get("status", "unknown"),
            "ts": alarm.get("createdTime", 0),
            "ts_human": datetime.fromtimestamp(
                alarm.get("createdTime", 0) / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC"),
            "details": alarm.get("details", {}),
        })
    return out


async def build_device_context(
    entity_id: str,
    widget_context: dict | None = None,
) -> dict:
    """
    Assemble full device context. Merges widget_context on top (more recent).
    Returns partial context with error flags on ThingsBoard failures.
    """
    redis = await _get_redis()
    cache_key = f"ctx:{entity_id}"

    # Try cache first
    try:
        cached = await redis.get(cache_key)
        if cached:
            ctx = json.loads(cached)
            if widget_context:
                ctx["latest_telemetry"].update(widget_context.get("latest_telemetry", {}))
                if widget_context.get("last_alarm"):
                    ctx["last_alarm_from_widget"] = widget_context["last_alarm"]
            return ctx
    except Exception as exc:
        logger.warning("Redis cache read failed: %s", exc)
    finally:
        await redis.aclose()

    tb: TBClient = get_tb_client()
    ctx: dict = {
        "entity_id": entity_id,
        "device_name": "unknown",
        "device_class": "unknown",
        "location": "unknown",
        "protocol": "unknown",
        "latest_telemetry": {},
        "telemetry_48hr_summary": {},
        "recent_alarms": [],
        "attributes": {},
        "errors": [],
    }

    # 1. Device metadata
    try:
        device = await tb.get_device(entity_id)
        ctx["device_name"] = device.get("name", entity_id)
        ctx["device_type"] = device.get("type", "unknown")
    except TBClientError as exc:
        ctx["errors"].append(f"device_metadata: {exc}")

    # 2. Shared attributes (device_class, location, protocol, baseline_days)
    try:
        attrs = await tb.get_device_attributes(entity_id)
        ctx["attributes"] = attrs
        ctx["device_class"] = attrs.get("device_class", "unknown")
        ctx["location"] = attrs.get("location", "unknown")
        ctx["protocol"] = attrs.get("protocol", "unknown")
    except TBClientError as exc:
        ctx["errors"].append(f"attributes: {exc}")

    # 3. Latest telemetry
    try:
        latest = await tb.get_latest_telemetry(entity_id)
        ctx["latest_telemetry"] = latest
    except TBClientError as exc:
        ctx["errors"].append(f"latest_telemetry: {exc}")

    # 4. 48-hour time series summary
    try:
        readings = await tb.get_telemetry(entity_id, limit=500)
        ctx["telemetry_48hr_summary"] = _summarise_timeseries(readings)
    except TBClientError as exc:
        ctx["errors"].append(f"telemetry_history: {exc}")

    # 5. Recent alarms
    try:
        alarms = await tb.get_alarms(entity_id, limit=5)
        ctx["recent_alarms"] = _format_alarms(alarms)
    except TBClientError as exc:
        ctx["errors"].append(f"alarms: {exc}")

    # Merge widget context (fresher data wins)
    if widget_context:
        ctx["latest_telemetry"].update(widget_context.get("latest_telemetry", {}))
        if widget_context.get("last_alarm"):
            ctx["last_alarm_from_widget"] = widget_context["last_alarm"]
        if widget_context.get("entity_name"):
            ctx["device_name"] = widget_context["entity_name"]

    # Cache result
    redis2 = await _get_redis()
    try:
        await redis2.set(cache_key, json.dumps(ctx, default=str), ex=CACHE_TTL)
    except Exception as exc:
        logger.warning("Redis cache write failed: %s", exc)
    finally:
        await redis2.aclose()

    if ctx["errors"]:
        logger.warning(
            "Device context for %s has %d error(s): %s",
            entity_id,
            len(ctx["errors"]),
            ctx["errors"],
        )

    return ctx
