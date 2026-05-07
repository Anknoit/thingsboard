"""
train_lstm.py — Train LSTM failure prediction models.

Generates synthetic sequences with realistic gradual degradation patterns
(bearing wear, power creep, vibration escalation) and trains one LSTM per
device class.

Usage:
    python train_lstm.py                         # train all classes
    python train_lstm.py --device-class hvac     # single class
    python train_lstm.py --epochs 50 --sequences 2000
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "fastapi"))

from config import settings          # noqa: E402
from services.predictive import (   # noqa: E402
    LSTM_FEATURE_SETS,
    LSTMPredictiveService,
    SEQ_LEN,
)

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)

DEVICE_CLASSES = list(LSTM_FEATURE_SETS.keys())
DEFAULT_SEQUENCES = 1500   # sequences per class
DEFAULT_EPOCHS    = 30


# ── Synthetic sequence generators ─────────────────────────────────────────────

def _time_of_day(i: int, interval_hours: float = 1.0) -> float:
    """Sinusoidal factor 0→1 representing time-of-day within a 24h cycle."""
    import math
    hour = (i * interval_hours) % 24
    return (math.sin(math.pi * (hour - 6) / 12) + 1) / 2


def gen_normal_sequence(device_class: str, length: int = SEQ_LEN) -> np.ndarray:
    """Generate a healthy operating sequence for the given device class."""
    features = LSTM_FEATURE_SETS.get(device_class, LSTM_FEATURE_SETS["hvac"])
    rows = []
    for i in range(length):
        tod = _time_of_day(i)
        if device_class == "hvac":
            row = [
                0.5 + 0.3 * tod + np.random.normal(0, 0.05),        # vibration_rms (mm/s)
                4.0 + 1.5 * tod + np.random.normal(0, 0.1),         # current_draw (A)
                20 + 5 * tod + np.random.normal(0, 0.3),             # temperature (°C)
                max(0, np.random.normal(0.2, 0.2)),                  # error_count
            ]
        elif device_class == "energy":
            biz = 1.0 if 8 <= (i % 24) < 18 else 0.1
            row = [
                40 + 80 * biz + np.random.normal(0, 3),              # current (A)
                15 + 40 * biz + np.random.normal(0, 1.5),            # active_power (kW)
                400 + np.random.normal(0, 2),                        # voltage (V)
                max(0, np.random.normal(0.1, 0.1)),                  # error_count
            ]
        elif device_class == "network":
            biz = 1.0 if 8 <= (i % 24) < 18 else 0.05
            row = [
                max(0, np.random.normal(0.02, 0.01)),                # error_rate (%)
                max(1, np.random.normal(5, 1.5)),                    # latency (ms)
                max(0, np.random.normal(0.01, 0.005)),               # packet_loss (%)
                (1e6 + 5e7 * biz) * np.random.uniform(0.7, 1.3),    # rx_bytes
            ]
        else:  # infra
            biz = 1.0 if 8 <= (i % 24) < 18 else 0.4
            row = [
                min(99, max(5, 20 + 40 * biz + np.random.normal(0, 5))),   # cpu_usage (%)
                45 + 15 * biz + np.random.normal(0, 2),                    # temperature (°C)
                10 + 50 * biz + np.random.normal(0, 5),                    # disk_io (MB/s)
                max(0, np.random.normal(0, 0.5)),                          # error_count
            ]
        rows.append(row[:len(features)])
    return np.array(rows, dtype=np.float32)


def gen_failure_sequence(device_class: str, length: int = SEQ_LEN) -> np.ndarray:
    """
    Generate a pre-failure sequence with gradual degradation over the window.
    The degradation accelerates toward the end of the sequence.
    """
    features = LSTM_FEATURE_SETS.get(device_class, LSTM_FEATURE_SETS["hvac"])
    base = gen_normal_sequence(device_class, length)

    for i in range(length):
        # Degradation factor: starts small, accelerates exponentially
        progress = i / length                     # 0.0 → 1.0
        severity = 0.1 + 0.9 * (progress ** 2)   # 0.1 → 1.0 accelerating

        if device_class == "hvac":
            # Bearing wear: vibration ↑, current ↑, temp ↑
            base[i, 0] *= (1 + 1.5 * severity)   # vibration_rms
            base[i, 1] *= (1 + 0.4 * severity)   # current_draw
            base[i, 2] += 15 * severity           # temperature
            base[i, 3] += 5 * severity            # error_count

        elif device_class == "energy":
            # PF degradation: current ↑, power ↑, errors ↑
            base[i, 0] *= (1 + 0.5 * severity)   # current
            base[i, 1] *= (1 + 0.3 * severity)   # active_power
            # voltage sags
            base[i, 2] -= 20 * severity           # voltage
            base[i, 3] += 10 * severity           # error_count

        elif device_class == "network":
            # Link degradation: errors ↑, latency ↑, packet loss ↑
            base[i, 0] = min(100, base[i, 0] * (1 + 30 * severity))  # error_rate
            base[i, 1] *= (1 + 8 * severity)                         # latency
            base[i, 2] = min(100, base[i, 2] * (1 + 20 * severity))  # packet_loss
            # rx_bytes drop as link fails
            base[i, 3] *= max(0.01, 1 - 0.8 * severity)

        else:  # infra
            # Resource exhaustion: cpu ↑, temp ↑
            base[i, 0] = min(99, base[i, 0] * (1 + 0.6 * severity))  # cpu_usage
            base[i, 1] += 25 * severity                               # temperature
            base[i, 2] *= (1 + 0.5 * severity)                        # disk_io
            base[i, 3] += 20 * severity                               # error_count

    return base.astype(np.float32)


# ── Dataset builder ───────────────────────────────────────────────────────────

def build_dataset(device_class: str, n_sequences: int) -> pd.DataFrame:
    """
    Build a DataFrame of flattened sequences with failure_in_72hr labels.
    50% normal, 50% pre-failure.
    """
    features = LSTM_FEATURE_SETS.get(device_class, LSTM_FEATURE_SETS["hvac"])
    n_normal  = n_sequences // 2
    n_failure = n_sequences - n_normal

    rows = []

    # Normal sequences
    for _ in range(n_normal):
        seq = gen_normal_sequence(device_class)
        # Each step is a row; only the last step has the label (windowed approach)
        for t, step in enumerate(seq):
            row = {f: float(step[i]) for i, f in enumerate(features)}
            row["failure_in_72hr"] = 0.0
            row["seq_id"] = len(rows) // SEQ_LEN
            rows.append(row)

    # Pre-failure sequences
    for _ in range(n_failure):
        seq = gen_failure_sequence(device_class)
        for t, step in enumerate(seq):
            row = {f: float(step[i]) for i, f in enumerate(features)}
            # Label 1 for the last 8 steps of a failure sequence (the critical window)
            row["failure_in_72hr"] = 1.0 if t >= SEQ_LEN - 8 else 0.0
            row["seq_id"] = len(rows) // SEQ_LEN
            rows.append(row)

    return pd.DataFrame(rows)


# ── Training ──────────────────────────────────────────────────────────────────

def train_class(device_class: str, n_sequences: int, epochs: int) -> None:
    print(f"\n{'='*55}")
    print(f"Training LSTM: device_class={device_class}")
    print(f"  sequences={n_sequences}  epochs={epochs}  seq_len={SEQ_LEN}")
    print(f"  features={LSTM_FEATURE_SETS[device_class]}")
    print(f"{'='*55}")

    df = build_dataset(device_class, n_sequences)
    total_rows = len(df)
    pos = int(df["failure_in_72hr"].sum())
    print(f"  Dataset: {total_rows} rows, {pos} positive ({100*pos/total_rows:.1f}%)")

    svc = LSTMPredictiveService()
    svc.train(device_class, df, epochs=epochs)

    model_path = Path(__file__).parent.parent / "fastapi" / "models" / f"lstm_{device_class}.pth"
    print(f"  ✓ Model saved: {model_path}")

    # Quick validation
    svc2 = LSTMPredictiveService()   # fresh instance — tests disk load
    bundle = svc2._load(device_class)
    if bundle:
        # Score a failure sequence
        fail_seq = gen_failure_sequence(device_class)
        X_scaled = bundle.scaler.transform(fail_seq)
        import torch
        X_t = torch.tensor(X_scaled, dtype=torch.float32).unsqueeze(0)
        bundle.model.eval()
        with torch.no_grad():
            prob = float(bundle.model(X_t).squeeze())
        threshold = settings.lstm_failure_threshold
        flag = "✓ DETECTED" if prob >= threshold else "✗ missed"
        print(f"  Failure validation: prob={prob:.3f} threshold={threshold} → {flag}")

        # Score a normal sequence
        norm_seq = gen_normal_sequence(device_class)
        X_n = bundle.scaler.transform(norm_seq)
        X_t_n = torch.tensor(X_n, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            prob_n = float(bundle.model(X_t_n).squeeze())
        flag_n = "✓ OK (normal)" if prob_n < threshold else "✗ false positive"
        print(f"  Normal  validation: prob={prob_n:.3f} threshold={threshold} → {flag_n}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Train LSTM predictive maintenance models")
    parser.add_argument(
        "--device-class",
        choices=DEVICE_CLASSES,
        help="Single device class to train (default: all)",
    )
    parser.add_argument(
        "--sequences",
        type=int,
        default=DEFAULT_SEQUENCES,
        help=f"Number of training sequences per class (default: {DEFAULT_SEQUENCES})",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=DEFAULT_EPOCHS,
        help=f"Training epochs (default: {DEFAULT_EPOCHS})",
    )
    args = parser.parse_args()

    classes = [args.device_class] if args.device_class else DEVICE_CLASSES

    print(f"LSTM training: {len(classes)} device class(es), {args.sequences} sequences, {args.epochs} epochs")

    for dc in classes:
        train_class(dc, args.sequences, args.epochs)

    print("\n[done] LSTM training complete.")
    print(f"       Run 'POST /debug/run-predictive' to trigger a batch job immediately.")


if __name__ == "__main__":
    main()
