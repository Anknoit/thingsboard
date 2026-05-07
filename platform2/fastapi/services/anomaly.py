"""
anomaly.py — Isolation Forest anomaly detection service.

One model per device_class. Models are trained offline via scripts/train_anomaly.py
or scripts/generate_synthetic_baseline.py, then loaded on first score() call.
"""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from models.schemas import AnomalyResult

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

# ── Feature definitions per device class ─────────────────────────────────────

FEATURE_SETS: dict[str, list[str]] = {
    "hvac":    ["temperature", "humidity", "power_consumption", "fan_speed", "co2_level"],
    "energy":  ["active_power", "reactive_power", "current", "voltage", "power_factor"],
    "network": ["rx_bytes", "tx_bytes", "error_rate", "latency", "packet_loss"],
    "infra":   ["cpu_usage", "memory_usage", "disk_io", "temperature", "error_count"],
    # Fallback for unknown classes — try to use whatever numerics are present
    "general": [],
}

# Human-readable units for explanation strings
FEATURE_UNITS: dict[str, str] = {
    "temperature": "°C",
    "humidity": "%",
    "power_consumption": "kW",
    "fan_speed": "RPM",
    "co2_level": "ppm",
    "active_power": "kW",
    "reactive_power": "kVAR",
    "current": "A",
    "voltage": "V",
    "power_factor": "",
    "rx_bytes": "B/s",
    "tx_bytes": "B/s",
    "error_rate": "%",
    "latency": "ms",
    "packet_loss": "%",
    "cpu_usage": "%",
    "memory_usage": "%",
    "disk_io": "MB/s",
    "error_count": "",
}


@dataclass
class _ModelBundle:
    """Everything needed to score a new sample."""
    model: IsolationForest
    scaler: StandardScaler
    feature_names: list[str]
    # Per-feature baseline stats for explanation generation
    feature_means: dict[str, float] = field(default_factory=dict)
    feature_stds: dict[str, float] = field(default_factory=dict)


# ── Core service ──────────────────────────────────────────────────────────────

class IsolationForestService:
    def __init__(self) -> None:
        self._cache: dict[str, _ModelBundle] = {}

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        device_class: str,
        training_data: list[dict],
        *,
        contamination: float = 0.05,
        n_estimators: int = 100,
    ) -> None:
        """
        Train an Isolation Forest for the given device_class.

        training_data: list of telemetry dicts e.g.
          [{"temperature": 22.4, "power_consumption": 4.1, ...}, ...]
        """
        feature_names = FEATURE_SETS.get(device_class, [])

        # For unknown classes, infer features from the data
        if not feature_names:
            sample_keys: set[str] = set()
            for row in training_data[:100]:
                sample_keys.update(k for k, v in row.items() if isinstance(v, (int, float)))
            feature_names = sorted(sample_keys)

        if not feature_names:
            logger.warning("No features for device_class=%s — skipping training", device_class)
            return

        # Extract feature matrix — skip rows missing all features
        rows: list[list[float]] = []
        for row in training_data:
            vals = [float(row.get(f, 0.0)) for f in feature_names]
            rows.append(vals)

        if len(rows) < 10:
            logger.warning(
                "Too few samples (%d) for device_class=%s — need at least 10",
                len(rows), device_class,
            )
            return

        X = np.array(rows, dtype=np.float32)

        # Compute per-feature stats before scaling (for explanation)
        means = {f: float(np.mean(X[:, i])) for i, f in enumerate(feature_names)}
        stds  = {f: float(np.std(X[:, i]) + 1e-9) for i, f in enumerate(feature_names)}

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_scaled)

        bundle = _ModelBundle(
            model=model,
            scaler=scaler,
            feature_names=feature_names,
            feature_means=means,
            feature_stds=stds,
        )

        # Persist to disk
        path = self._model_path(device_class)
        os.makedirs(MODEL_DIR, exist_ok=True)
        joblib.dump(bundle, path)
        self._cache[device_class] = bundle

        logger.info(
            "Anomaly model trained: device_class=%s samples=%d features=%s → %s",
            device_class, len(rows), feature_names, path,
        )

    # ── Scoring ───────────────────────────────────────────────────────────────

    def score(
        self,
        entity_id: str,
        device_class: str,
        telemetry: dict,
    ) -> AnomalyResult:
        """
        Score a single telemetry snapshot.
        Returns AnomalyResult with plain-English explanation.
        Falls back gracefully if no model is trained yet.
        """
        bundle = self._load(device_class)

        if bundle is None:
            return AnomalyResult(
                entity_id=entity_id,
                device_class=device_class,
                score=0.0,
                sigma=0.0,
                is_anomaly=False,
                explanation=f"No anomaly model trained for device_class='{device_class}' yet.",
                features_used={},
                scored_at=datetime.now(timezone.utc),
            )

        # Extract features
        features_used: dict[str, float] = {}
        row: list[float] = []
        for f in bundle.feature_names:
            val = float(telemetry.get(f, bundle.feature_means.get(f, 0.0)))
            features_used[f] = val
            row.append(val)

        X = np.array([row], dtype=np.float32)
        X_scaled = bundle.scaler.transform(X)

        # Raw IF score: negative = more anomalous; range roughly [-0.5, 0.5]
        raw_score = float(bundle.model.score_samples(X_scaled)[0])
        # Convert to 0–100 (higher = more anomalous)
        anomaly_score = round(max(0.0, min(100.0, (-raw_score + 0.5) * 200)), 1)

        # IF decision: -1 = anomaly, 1 = normal
        prediction = int(bundle.model.predict(X_scaled)[0])
        is_anomaly = prediction == -1

        # Find the most deviant feature for explanation
        sigmas: dict[str, float] = {}
        for f, val in features_used.items():
            mean = bundle.feature_means.get(f, 0.0)
            std  = bundle.feature_stds.get(f, 1.0)
            sigmas[f] = abs(val - mean) / std

        max_sigma_feature = max(sigmas, key=sigmas.get) if sigmas else None
        max_sigma = sigmas.get(max_sigma_feature, 0.0) if max_sigma_feature else 0.0

        explanation = self._build_explanation(
            is_anomaly, max_sigma_feature, features_used,
            bundle.feature_means, bundle.feature_stds, max_sigma,
        )

        return AnomalyResult(
            entity_id=entity_id,
            device_class=device_class,
            score=anomaly_score,
            sigma=round(max_sigma, 2),
            is_anomaly=is_anomaly,
            explanation=explanation,
            features_used=features_used,
            scored_at=datetime.now(timezone.utc),
        )

    # ── Explanation builder ───────────────────────────────────────────────────

    def _build_explanation(
        self,
        is_anomaly: bool,
        feature: str | None,
        values: dict[str, float],
        means: dict[str, float],
        stds: dict[str, float],
        sigma: float,
    ) -> str:
        if not is_anomaly or feature is None:
            return "Readings are within normal operating range."

        val  = values.get(feature, 0.0)
        mean = means.get(feature, 0.0)
        unit = FEATURE_UNITS.get(feature, "")
        diff_pct = abs(val - mean) / (abs(mean) + 1e-9) * 100

        direction = "above" if val > mean else "below"
        label = feature.replace("_", " ").title()

        baseline_days = settings_baseline_days()
        return (
            f"{label} is {sigma:.1f}σ {direction} {baseline_days}-day baseline "
            f"({val:.2f}{unit} vs normal {mean:.2f}{unit}, "
            f"{diff_pct:.0f}% {'higher' if val > mean else 'lower'} than normal)."
        ).strip()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _model_path(self, device_class: str) -> str:
        return os.path.join(MODEL_DIR, f"isolation_forest_{device_class}.pkl")

    def _load(self, device_class: str) -> _ModelBundle | None:
        if device_class in self._cache:
            return self._cache[device_class]

        path = self._model_path(device_class)
        if not os.path.exists(path):
            logger.debug("No model file for device_class=%s at %s", device_class, path)
            return None

        try:
            bundle = joblib.load(path)
            self._cache[device_class] = bundle
            logger.info("Anomaly model loaded: device_class=%s", device_class)
            return bundle
        except Exception as exc:
            logger.error("Failed to load anomaly model for %s: %s", device_class, exc)
            return None

    def loaded_classes(self) -> list[str]:
        """Return device classes for which a model file exists."""
        if not os.path.isdir(MODEL_DIR):
            return []
        return [
            dc for dc in FEATURE_SETS
            if os.path.exists(self._model_path(dc))
        ]


# Lazy import — only needed at explanation time
def settings_baseline_days() -> int:
    try:
        from config import settings
        return settings.anomaly_baseline_days
    except Exception:
        return 30


# ── Module-level singleton ────────────────────────────────────────────────────

_service: IsolationForestService | None = None


def get_anomaly_service() -> IsolationForestService:
    global _service
    if _service is None:
        _service = IsolationForestService()
    return _service
