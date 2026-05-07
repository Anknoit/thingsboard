"""
Isolation Forest anomaly detection — stub.
Full implementation in Phase 5.
"""

import logging
import os
from datetime import datetime, timezone

from models.schemas import AnomalyResult

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

FEATURE_SETS = {
    "hvac":    ["temperature", "humidity", "power_consumption", "fan_speed", "co2_level"],
    "energy":  ["active_power", "reactive_power", "current", "voltage", "power_factor"],
    "network": ["rx_bytes", "tx_bytes", "error_rate", "latency", "packet_loss"],
    "infra":   ["cpu_usage", "memory_usage", "disk_io", "temperature", "error_count"],
}


class IsolationForestService:
    def __init__(self) -> None:
        self._models: dict = {}

    def score(self, entity_id: str, device_class: str, telemetry: dict) -> AnomalyResult:
        """
        Phase 5 replaces this with real Isolation Forest inference.
        Stub returns a neutral (non-anomaly) score.
        """
        return AnomalyResult(
            entity_id=entity_id,
            device_class=device_class,
            score=0.0,
            sigma=0.0,
            is_anomaly=False,
            explanation="Anomaly detection model not yet trained (Phase 5).",
            features_used={},
            scored_at=datetime.now(timezone.utc),
        )


_service: IsolationForestService | None = None


def get_anomaly_service() -> IsolationForestService:
    global _service
    if _service is None:
        _service = IsolationForestService()
    return _service
