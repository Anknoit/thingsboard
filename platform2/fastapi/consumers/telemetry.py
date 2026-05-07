"""
Kafka telemetry consumer — scores every incoming message for anomalies.

Full implementation in Phase 5. This stub starts cleanly and is replaced
when the anomaly service is available.
"""

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
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


class TelemetryConsumer:
    def __init__(self) -> None:
        self._running = False
        self._consumer: AIOKafkaConsumer | None = None

    def stop(self) -> None:
        self._running = False

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
                    enable_auto_commit=True,
                    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                )
                await self._consumer.start()
                logger.info("Telemetry consumer connected")

                async for msg in self._consumer:
                    if not self._running:
                        break
                    await self._process(msg.value, msg.topic)

            except KafkaConnectionError as exc:
                logger.warning("Kafka unavailable: %s — retrying in 10s", exc)
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Telemetry consumer error — restarting in 5s")
                await asyncio.sleep(5)
            finally:
                if self._consumer:
                    try:
                        await self._consumer.stop()
                    except Exception:
                        pass

        logger.info("Telemetry consumer stopped")

    async def _process(self, payload: dict, topic: str) -> None:
        """
        Phase 5 will replace this with full anomaly scoring + DB write.
        For now, log receipt and pass.
        """
        entity_id = payload.get("device_id", "unknown")
        device_class = payload.get("device_class", "unknown")
        logger.debug(
            "telemetry received: entity=%s class=%s topic=%s",
            entity_id,
            device_class,
            topic,
        )

        # ── Phase 5: anomaly scoring ─────────────────────────────────────────
        # try:
        #     from services.anomaly import get_anomaly_service
        #     import asyncio
        #     service = get_anomaly_service()
        #     result = await asyncio.get_event_loop().run_in_executor(
        #         None, service.score, entity_id, device_class, payload.get("telemetry", {})
        #     )
        #     if result.is_anomaly:
        #         ... create alarm, enrich, write to DB ...
        # except Exception:
        #     logger.exception("Anomaly scoring failed for %s", entity_id)
        pass
