"""
telemetry.py — Kafka consumer that scores every incoming telemetry message
for anomalies and writes results to TimescaleDB + NavNet Registry.

Topics consumed (all device classes):
  navnet.telemetry.bms.hvac
  navnet.telemetry.bms.energy
  navnet.telemetry.bms.other
  navnet.telemetry.nms.network
  navnet.telemetry.nms.infra

Consumer group: platform2-anomaly
Dead-letter queue: platform2.dlq  (malformed / unprocessable messages)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from config import settings

logger = logging.getLogger(__name__)

TOPICS = [
    settings.kafka_topics_bms_hvac,
    settings.kafka_topics_bms_energy,
    settings.kafka_topics_bms_other,
    settings.kafka_topics_nms_network,
    settings.kafka_topics_nms_infra,
]
DLQ_TOPIC = "platform2.dlq"
ACTIVE_ALARM_TTL = 300  # seconds — how long to remember active alarm per device


class TelemetryConsumer:
    def __init__(self) -> None:
        self._running = False
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None

    def stop(self) -> None:
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        logger.info("Telemetry consumer starting — topics: %s", TOPICS)

        while self._running:
            try:
                self._consumer = AIOKafkaConsumer(
                    *TOPICS,
                    bootstrap_servers=settings.kafka_bootstrap,
                    group_id="platform2-anomaly",
                    auto_offset_reset="latest",
                    enable_auto_commit=False,          # manual commit after processing
                    value_deserializer=lambda v: v,    # raw bytes — we parse ourselves
                    max_poll_records=50,
                )
                self._producer = AIOKafkaProducer(
                    bootstrap_servers=settings.kafka_bootstrap,
                    value_serializer=lambda v: json.dumps(v).encode(),
                )
                await self._consumer.start()
                await self._producer.start()
                logger.info("Telemetry consumer connected to Kafka")

                async for msg in self._consumer:
                    if not self._running:
                        break
                    await self._handle_message(msg)
                    await self._consumer.commit()

            except KafkaConnectionError as exc:
                logger.warning("Kafka unavailable: %s — retrying in 10s", exc)
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Telemetry consumer error — restarting in 5s")
                await asyncio.sleep(5)
            finally:
                await self._cleanup()

        logger.info("Telemetry consumer stopped")

    async def _cleanup(self) -> None:
        for obj in (self._consumer, self._producer):
            if obj:
                try:
                    await obj.stop()
                except Exception:
                    pass
        self._consumer = None
        self._producer = None

    # ── Per-message handler ───────────────────────────────────────────────────

    async def _handle_message(self, msg) -> None:
        raw = msg.value

        # Parse JSON
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            logger.warning("Malformed message on %s — sending to DLQ: %s", msg.topic, exc)
            await self._dlq(raw, str(exc))
            return

        entity_id    = payload.get("device_id", "")
        device_class = payload.get("device_class", "unknown")
        device_name  = payload.get("device_name", entity_id)
        telemetry    = payload.get("telemetry", {})

        if not entity_id or not isinstance(telemetry, dict):
            await self._dlq(raw, "missing device_id or telemetry")
            return

        # Score for anomaly
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                _score, entity_id, device_class, telemetry,
            )
        except Exception as exc:
            logger.exception("Anomaly scoring failed for %s: %s", entity_id, exc)
            return

        # Write to TimescaleDB
        try:
            await _write_anomaly_score(result)
        except Exception as exc:
            logger.warning("DB write failed for %s: %s", entity_id, exc)

        # If anomaly detected — enrich alarm or create one
        if result.is_anomaly:
            logger.info(
                "ANOMALY entity=%s class=%s score=%.1f sigma=%.2f: %s",
                entity_id, device_class, result.score, result.sigma, result.explanation,
            )
            await self._handle_anomaly(entity_id, device_class, device_name, result)

    # ── Anomaly handling ──────────────────────────────────────────────────────

    async def _handle_anomaly(
        self,
        entity_id: str,
        device_class: str,
        device_name: str,
        result,
    ) -> None:
        from services.registry_client import get_registry_client
        tb = get_registry_client()

        enrichment = {
            "ai_anomaly_score": result.score,
            "ai_sigma": result.sigma,
            "ai_explanation": result.explanation,
            "ai_scored_at": result.scored_at.isoformat(),
        }

        # Check Redis for active alarm on this device
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            alarm_id = await redis.get(f"active_alarm:{entity_id}")

            if alarm_id:
                # Enrich existing alarm
                try:
                    await tb.set_device_server_attributes(entity_id, enrichment)
                    logger.debug("Enriched alarm %s for entity %s", alarm_id, entity_id)
                except Exception as exc:
                    logger.warning("Failed to enrich alarm for %s: %s", entity_id, exc)
            else:
                # No active alarm — create one
                try:
                    new_alarm_id = await tb.create_alarm(
                        entity_id=entity_id,
                        alarm_type="AI_ANOMALY_DETECTED",
                        severity=_severity_from_score(result.score),
                        details={
                            "device_class": device_class,
                            "ai_anomaly_score": result.score,
                            "ai_sigma": result.sigma,
                            "ai_explanation": result.explanation,
                            "features": result.features_used,
                        },
                    )
                    # Cache alarm reference
                    await redis.set(
                        f"active_alarm:{entity_id}",
                        new_alarm_id,
                        ex=ACTIVE_ALARM_TTL,
                    )
                    # Also write enrichment as server attributes
                    await tb.set_device_server_attributes(entity_id, enrichment)
                    logger.info(
                        "Created anomaly alarm %s for entity %s (score=%.1f)",
                        new_alarm_id, entity_id, result.score,
                    )
                except Exception as exc:
                    logger.warning("Failed to create anomaly alarm for %s: %s", entity_id, exc)
        finally:
            await redis.aclose()

    # ── Dead-letter queue ─────────────────────────────────────────────────────

    async def _dlq(self, raw: bytes, reason: str) -> None:
        if self._producer is None:
            return
        try:
            await self._producer.send(
                DLQ_TOPIC,
                value={"raw": raw.decode("utf-8", errors="replace"), "reason": reason},
            )
        except Exception as exc:
            logger.warning("DLQ send failed: %s", exc)


# ── Helpers (module-level, called via executor) ───────────────────────────────

def _score(entity_id: str, device_class: str, telemetry: dict):
    from services.anomaly import get_anomaly_service
    return get_anomaly_service().score(entity_id, device_class, telemetry)


def _severity_from_score(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "MAJOR"
    if score >= 40:
        return "WARNING"
    return "INDETERMINATE"


async def _write_anomaly_score(result) -> None:
    """Write an AnomalyResult to the anomaly_scores TimescaleDB hypertable."""
    from db.postgres import AsyncSessionLocal, AnomalyScore
    async with AsyncSessionLocal() as session:
        row = AnomalyScore(
            entity_id=result.entity_id,
            scored_at=result.scored_at,
            score=result.score,
            sigma=result.sigma,
            triggered=result.is_anomaly,
            telemetry_snapshot=result.features_used,
        )
        session.add(row)
        await session.commit()
