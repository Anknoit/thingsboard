"""
predictive.py — LSTM predictive maintenance service.

Predicts equipment failure 24-72 hours ahead using a 2-layer LSTM
trained on sequences of hourly telemetry readings.

Architecture:
  Input  → LSTM(64) → LSTM(32) → Linear(1) → Sigmoid → failure_probability
  Sequence length: 24 time steps (24 hours of hourly data)
  Features: 4 per device class (vibration_rms, current_draw, temperature, error_count)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler

from config import settings
from models.schemas import PredictiveResult

logger = logging.getLogger(__name__)

MODEL_DIR = "/trained_models"
SEQ_LEN = 24        # 24 hourly readings = 24-hour look-back window
N_FEATURES = 4      # fixed across all device classes

# ── Feature definitions per device class ─────────────────────────────────────

LSTM_FEATURE_SETS: dict[str, list[str]] = {
    "hvac":    ["vibration_rms", "current_draw", "temperature", "error_count"],
    "energy":  ["current",       "active_power", "voltage",     "error_count"],
    "network": ["error_rate",    "latency",      "packet_loss", "rx_bytes"],
    "infra":   ["cpu_usage",     "temperature",  "disk_io",     "error_count"],
    # elevator and other BMS devices fall back to hvac feature set
}

# Work order templates per device class — parts, safety requirements
WO_TEMPLATES: dict[str, dict] = {
    "hvac": {
        "skill_level": "HVAC Technician (Level 2)",
        "safety_prerequisites": [
            "Isolate power at MCC — LOTO procedure ref. LOTO-HVAC-01",
            "Allow 15 minutes for capacitors to discharge",
            "Wear arc-flash PPE (Cat 2 minimum)",
        ],
        "parts": [
            {"name": "Supply fan motor bearing",   "stock_code": "BRG-6206-2RS",    "qty": 2},
            {"name": "Motor coupling",             "stock_code": "CPL-FLEX-25MM",   "qty": 1},
            {"name": "Vibration isolation mount",  "stock_code": "VIB-ISO-M10",     "qty": 4},
            {"name": "Grease cartridge (Polyrex)", "stock_code": "LUB-POLYREX-EM",  "qty": 1},
        ],
        "estimated_labour_hours": 4.5,
    },
    "energy": {
        "skill_level": "Licensed Electrician (HV)",
        "safety_prerequisites": [
            "Notify utility provider if working upstream of main breaker",
            "Isolate and lock out distribution board",
            "Test for voltage before touching bus bars",
        ],
        "parts": [
            {"name": "CT sensor (200A)",        "stock_code": "CT-200A-5A",     "qty": 3},
            {"name": "Power factor capacitor",  "stock_code": "CAP-50KVAR-415V","qty": 1},
            {"name": "Circuit breaker (125A)",  "stock_code": "MCB-125A-3P",    "qty": 1},
        ],
        "estimated_labour_hours": 3.0,
    },
    "network": {
        "skill_level": "Network Engineer (CCNP or equivalent)",
        "safety_prerequisites": [
            "Schedule maintenance window — notify NOC team",
            "Ensure failover path is active before touching primary link",
        ],
        "parts": [
            {"name": "SFP+ 10G transceiver",  "stock_code": "SFP-10G-SR",      "qty": 2},
            {"name": "Fibre patch lead (LC)",  "stock_code": "FIB-LC-LC-3M-OM3","qty": 2},
            {"name": "Fibre connector cleaner","stock_code": "FCC-125",          "qty": 1},
        ],
        "estimated_labour_hours": 2.0,
    },
    "infra": {
        "skill_level": "Systems Administrator / Data Centre Technician",
        "safety_prerequisites": [
            "Ensure live migration of workloads before hardware maintenance",
            "Anti-static wrist strap required when handling components",
        ],
        "parts": [
            {"name": "Server cooling fan",  "stock_code": "FAN-4056-12V",   "qty": 4},
            {"name": "Thermal compound",    "stock_code": "TX-4-SYRINGE",   "qty": 1},
            {"name": "DIMM (32GB DDR5)",    "stock_code": "RAM-32G-DDR5",   "qty": 1},
        ],
        "estimated_labour_hours": 2.5,
    },
}


# ── PyTorch model definition ──────────────────────────────────────────────────

class FailureLSTM(nn.Module):
    def __init__(self, n_features: int = N_FEATURES):
        super().__init__()
        self.lstm1 = nn.LSTM(
            input_size=n_features,
            hidden_size=64,
            num_layers=1,
            batch_first=True,
            dropout=0.0,
        )
        self.lstm2 = nn.LSTM(
            input_size=64,
            hidden_size=32,
            num_layers=1,
            batch_first=True,
            dropout=0.0,
        )
        self.dropout = nn.Dropout(0.2)
        self.fc = nn.Linear(32, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, n_features)
        out, _ = self.lstm1(x)
        out, _ = self.lstm2(out)
        out = self.dropout(out[:, -1, :])   # take last time step
        return self.sigmoid(self.fc(out))


@dataclass
class _LSTMBundle:
    model: FailureLSTM
    scaler: MinMaxScaler
    feature_names: list[str]
    device_class: str


# ── Main service ──────────────────────────────────────────────────────────────

class LSTMPredictiveService:
    def __init__(self) -> None:
        self._cache: dict[str, _LSTMBundle] = {}

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        device_class: str,
        training_data: "pd.DataFrame",  # noqa: F821
        *,
        epochs: int = 30,
        batch_size: int = 32,
        learning_rate: float = 1e-3,
    ) -> None:
        """
        Train the LSTM on a DataFrame with columns matching LSTM_FEATURE_SETS[device_class]
        plus a 'failure_in_72hr' binary label column.
        """
        import pandas as pd

        feature_names = LSTM_FEATURE_SETS.get(device_class, LSTM_FEATURE_SETS["hvac"])

        df = training_data.copy()
        missing = [f for f in feature_names if f not in df.columns]
        if missing:
            logger.warning("Missing features for %s: %s — filling with 0", device_class, missing)
            for f in missing:
                df[f] = 0.0

        X_raw = df[feature_names].values.astype(np.float32)
        y_raw = df["failure_in_72hr"].values.astype(np.float32) if "failure_in_72hr" in df.columns else np.zeros(len(df), dtype=np.float32)

        scaler = MinMaxScaler()
        X_scaled = scaler.fit_transform(X_raw)

        # Build sequences
        seqs, labels = [], []
        for i in range(len(X_scaled) - SEQ_LEN):
            seqs.append(X_scaled[i : i + SEQ_LEN])
            labels.append(y_raw[i + SEQ_LEN])

        if len(seqs) < batch_size:
            logger.warning("Too few sequences (%d) to train LSTM for %s", len(seqs), device_class)
            return

        X_t = torch.tensor(np.array(seqs), dtype=torch.float32)
        y_t = torch.tensor(np.array(labels), dtype=torch.float32).unsqueeze(1)

        model = FailureLSTM(n_features=len(feature_names))
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        criterion = nn.BCELoss()

        # Class weighting for imbalanced labels
        n_pos = float(y_t.sum())
        n_neg = float(len(y_t) - n_pos)
        pos_weight = torch.tensor([n_neg / (n_pos + 1e-9)])
        weighted_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        model.train()
        dataset = torch.utils.data.TensorDataset(X_t, y_t)
        loader  = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        for epoch in range(epochs):
            total_loss = 0.0
            for X_batch, y_batch in loader:
                optimizer.zero_grad()
                preds = model(X_batch)
                loss  = criterion(preds, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                total_loss += loss.item()
            if (epoch + 1) % 10 == 0:
                logger.info("LSTM [%s] epoch %d/%d loss=%.4f", device_class, epoch + 1, epochs, total_loss / len(loader))

        model.eval()
        bundle = _LSTMBundle(model=model, scaler=scaler, feature_names=feature_names, device_class=device_class)

        os.makedirs(MODEL_DIR, exist_ok=True)
        model_path = self._model_path(device_class)
        torch.save(model.state_dict(), model_path)
        joblib.dump({"scaler": scaler, "feature_names": feature_names, "device_class": device_class}, self._meta_path(device_class))

        self._cache[device_class] = bundle
        logger.info("LSTM trained and saved: device_class=%s sequences=%d → %s", device_class, len(seqs), model_path)

    # ── Scoring ───────────────────────────────────────────────────────────────

    async def score_device(
        self,
        entity_id: str,
        device_class: str,
    ) -> PredictiveResult | None:
        """
        Fetch last 24 hours of hourly telemetry from NavNet Registry and score
        with the LSTM. Returns None if data or model is unavailable.
        """
        bundle = self._load(device_class)
        if bundle is None:
            logger.debug("No LSTM model for device_class=%s", device_class)
            return None

        # Fetch 24hr telemetry from NavNet Registry
        from services.registry_client import get_registry_client
        import time as _time

        tb = get_registry_client()
        now_ms   = int(_time.time() * 1000)
        start_ms = now_ms - 26 * 3600 * 1000  # 26hr buffer

        try:
            readings = await tb.get_telemetry(
                entity_id,
                keys=bundle.feature_names,
                start_ts=start_ms,
                end_ts=now_ms,
                limit=200,
            )
        except Exception as exc:
            logger.warning("Failed to fetch telemetry for LSTM scoring of %s: %s", entity_id, exc)
            return None

        if len(readings) < SEQ_LEN:
            logger.debug("Insufficient readings (%d < %d) for %s", len(readings), SEQ_LEN, entity_id)
            return None

        # Build feature matrix from most recent SEQ_LEN readings
        recent = readings[-SEQ_LEN:]
        rows: list[list[float]] = []
        for pt in recent:
            vals = pt.get("values", {})
            row  = [float(vals.get(f, 0.0)) for f in bundle.feature_names]
            rows.append(row)

        X_raw    = np.array(rows, dtype=np.float32)
        X_scaled = bundle.scaler.transform(X_raw)
        X_t      = torch.tensor(X_scaled, dtype=torch.float32).unsqueeze(0)  # (1, 24, F)

        bundle.model.eval()
        with torch.no_grad():
            prob = float(bundle.model(X_t).squeeze())

        # Determine predicted failure window from probability
        if prob >= 0.90:
            window = "24hr"
        elif prob >= 0.80:
            window = "48hr"
        else:
            window = "72hr"

        # Contributing features — compute gradient-like attribution via simple diff
        contributing = self._feature_attribution(bundle, X_scaled)

        return PredictiveResult(
            entity_id=entity_id,
            device_class=device_class,
            failure_probability=round(prob, 4),
            predicted_failure_window=window,
            contributing_features=contributing,
            confidence=round(min(1.0, prob * 1.3), 3),
            scored_at=datetime.now(timezone.utc),
        )

    def generate_work_order_data(
        self,
        entity_id: str,
        result: PredictiveResult,
    ) -> dict:
        """Return structured work order payload based on device_class failure signature."""
        dc = result.device_class
        tmpl = WO_TEMPLATES.get(dc, WO_TEMPLATES["hvac"])

        top_feature = (
            max(result.contributing_features, key=result.contributing_features.get)
            if result.contributing_features else "unknown"
        ).replace("_", " ")

        window = result.predicted_failure_window
        priority = 1 if window == "24hr" else (2 if window == "48hr" else 3)

        return {
            "fault_description": (
                f"Predictive model indicates {result.failure_probability*100:.0f}% probability "
                f"of {dc.upper()} failure within {window}. "
                f"Primary indicator: {top_feature}."
            ),
            "steps": [
                f"Review equipment health dashboard for {entity_id}",
                f"Inspect {top_feature} — compare against baseline spec",
                "Check all mechanical connections and fasteners",
                "Perform full diagnostic per manufacturer checklist",
                *[f"Replace: {p['name']}" for p in tmpl["parts"][:2]],
                "Test run under load and verify all parameters within spec",
                "Update maintenance log and reset health counters",
            ],
            "parts": tmpl["parts"],
            "labour_hours": tmpl["estimated_labour_hours"],
            "priority": priority,
            "skill_level": tmpl["skill_level"],
            "safety_prerequisites": tmpl["safety_prerequisites"],
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _feature_attribution(
        self,
        bundle: _LSTMBundle,
        X_scaled: np.ndarray,
    ) -> dict[str, float]:
        """
        Simple mean-absolute-deviation attribution per feature
        across the sequence (proxy for importance).
        """
        contributions: dict[str, float] = {}
        for i, fname in enumerate(bundle.feature_names):
            col = X_scaled[:, i]
            contributions[fname] = round(float(np.std(col)), 4)
        # Normalise to sum to 1
        total = sum(contributions.values()) or 1.0
        return {k: round(v / total, 4) for k, v in contributions.items()}

    def _model_path(self, dc: str) -> str:
        return os.path.join(MODEL_DIR, f"lstm_{dc}.pth")

    def _meta_path(self, dc: str) -> str:
        return os.path.join(MODEL_DIR, f"lstm_{dc}_meta.pkl")

    def _load(self, dc: str) -> _LSTMBundle | None:
        if dc in self._cache:
            return self._cache[dc]

        model_path = self._model_path(dc)
        meta_path  = self._meta_path(dc)

        if not os.path.exists(model_path) or not os.path.exists(meta_path):
            return None

        try:
            meta = joblib.load(meta_path)
            feature_names: list[str] = meta["feature_names"]
            model = FailureLSTM(n_features=len(feature_names))
            model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
            model.eval()
            bundle = _LSTMBundle(
                model=model,
                scaler=meta["scaler"],
                feature_names=feature_names,
                device_class=dc,
            )
            self._cache[dc] = bundle
            logger.info("LSTM model loaded: device_class=%s", dc)
            return bundle
        except Exception as exc:
            logger.error("Failed to load LSTM model for %s: %s", dc, exc)
            return None


# ── Module-level singleton ────────────────────────────────────────────────────

_service: LSTMPredictiveService | None = None


def get_predictive_service() -> LSTMPredictiveService:
    global _service
    if _service is None:
        _service = LSTMPredictiveService()
    return _service
