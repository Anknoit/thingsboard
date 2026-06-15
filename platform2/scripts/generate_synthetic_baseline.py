"""
generate_synthetic_baseline.py — Generate 30 days of synthetic telemetry,
train Isolation Forest models, and optionally publish to NavNet Registry via MQTT.

Useful before real device data is available (e.g. at first deployment).

Usage:
    # Generate data and train models only
    python generate_synthetic_baseline.py

    # Also publish to NavNet Registry so dashboards show history
    python generate_synthetic_baseline.py --publish --credentials credentials.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "fastapi"))

from config import settings  # noqa: E402

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

DAYS = 30
INTERVAL_SECONDS = 300   # one reading every 5 minutes
ANOMALIES_PER_CLASS = 3  # injected outliers for validation


# ── Seasonality helpers ───────────────────────────────────────────────────────

def time_of_day_factor(ts: datetime) -> float:
    """Returns 0.0 (midnight) to 1.0 (noon) sinusoidal day factor."""
    hour_frac = ts.hour + ts.minute / 60.0
    return (math.sin(math.pi * (hour_frac - 6) / 12) + 1) / 2


def is_business_hours(ts: datetime) -> bool:
    return 8 <= ts.hour < 18 and ts.weekday() < 5


# ── Per-class sample generators ───────────────────────────────────────────────

def gen_hvac(ts: datetime, anomaly: bool = False) -> dict[str, float]:
    tod = time_of_day_factor(ts)
    temp              = 18 + 6 * tod + random.gauss(0, 0.4)
    humidity          = 45 + 15 * (1 - tod) + random.gauss(0, 1.5)
    power_consumption = 2 + 3 * tod + random.gauss(0, 0.15)
    fan_speed         = 800 + 600 * tod + random.gauss(0, 30)
    co2_level         = 400 + 400 * (1 if is_business_hours(ts) else 0.1) + random.gauss(0, 20)

    if anomaly:
        power_consumption *= random.uniform(1.25, 1.45)   # bearing wear power spike
        fan_speed         *= random.uniform(0.7, 0.85)    # reduced airflow
    return {
        "temperature": round(temp, 2),
        "humidity": round(humidity, 2),
        "power_consumption": round(power_consumption, 3),
        "fan_speed": round(fan_speed, 1),
        "co2_level": round(co2_level, 1),
    }


def gen_energy(ts: datetime, anomaly: bool = False) -> dict[str, float]:
    biz = 1.0 if is_business_hours(ts) else 0.15
    active_power   = 10 + 40 * biz + random.gauss(0, 1.5)
    reactive_power = active_power * 0.3 + random.gauss(0, 0.5)
    current        = active_power / 0.4 + random.gauss(0, 0.5)   # ~400V three-phase
    voltage        = 400 + random.gauss(0, 2)
    power_factor   = 0.92 + random.gauss(0, 0.02)

    if anomaly:
        power_factor  -= random.uniform(0.12, 0.20)   # PF degradation
        reactive_power *= random.uniform(1.5, 2.0)
    return {
        "active_power": round(active_power, 2),
        "reactive_power": round(reactive_power, 2),
        "current": round(current, 2),
        "voltage": round(voltage, 1),
        "power_factor": round(min(1.0, max(0.0, power_factor)), 3),
    }


def gen_network(ts: datetime, anomaly: bool = False) -> dict[str, float]:
    biz       = 1.0 if is_business_hours(ts) else 0.1
    rx_bytes  = (1_000_000 + 99_000_000 * biz) * random.uniform(0.7, 1.3)
    tx_bytes  = rx_bytes * random.uniform(0.3, 0.7)
    error_rate = max(0, random.gauss(0.02, 0.01))
    latency    = max(1, random.gauss(5, 1.5))
    packet_loss = max(0, random.gauss(0.01, 0.005))

    if anomaly:
        error_rate  *= random.uniform(40, 80)     # port fault
        packet_loss *= random.uniform(50, 100)
        latency     *= random.uniform(8, 15)
    return {
        "rx_bytes": round(rx_bytes, 0),
        "tx_bytes": round(tx_bytes, 0),
        "error_rate": round(error_rate, 4),
        "latency": round(latency, 2),
        "packet_loss": round(packet_loss, 4),
    }


def gen_infra(ts: datetime, anomaly: bool = False) -> dict[str, float]:
    biz        = 1.0 if is_business_hours(ts) else 0.4
    cpu_usage  = 20 + 40 * biz + random.gauss(0, 5)
    mem_usage  = 45 + 20 * biz + random.gauss(0, 3)
    disk_io    = 10 + 50 * biz + random.gauss(0, 5)
    temperature = 45 + 10 * (cpu_usage / 80) + random.gauss(0, 1.5)
    error_count = max(0, random.gauss(0, 1))

    if anomaly:
        cpu_usage   = min(99, cpu_usage * random.uniform(1.6, 1.9))
        temperature += random.uniform(20, 30)
        error_count += random.randint(50, 200)
    return {
        "cpu_usage": round(min(100, max(0, cpu_usage)), 1),
        "memory_usage": round(min(100, max(0, mem_usage)), 1),
        "disk_io": round(max(0, disk_io), 1),
        "temperature": round(temperature, 1),
        "error_count": round(max(0, error_count), 0),
    }


# Occupancy/elevator/fire use 'other' topic — map to generic device_class
def gen_occupancy(ts: datetime, anomaly: bool = False) -> dict[str, float]:
    biz = 1.0 if is_business_hours(ts) else 0.05
    return {
        "occupancy_count": max(0, round(50 * biz + random.gauss(0, 5))),
        "door_events": max(0, round(20 * biz + random.gauss(0, 3))),
    }


GENERATORS: dict[str, Any] = {
    "hvac":    gen_hvac,
    "energy":  gen_energy,
    "network": gen_network,
    "infra":   gen_infra,
}


# ── Data generation ───────────────────────────────────────────────────────────

def generate_dataset(device_class: str, days: int) -> list[dict]:
    gen = GENERATORS[device_class]
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    total_steps = int(days * 86400 / INTERVAL_SECONDS)
    # Choose random anomaly insertion indices
    anomaly_indices = set(random.sample(range(total_steps), min(ANOMALIES_PER_CLASS, total_steps)))

    samples = []
    for i in range(total_steps):
        ts = start + timedelta(seconds=i * INTERVAL_SECONDS)
        anomaly = i in anomaly_indices
        sample = gen(ts, anomaly=anomaly)
        samples.append(sample)

    return samples


# ── MQTT publisher (optional) ─────────────────────────────────────────────────

def publish_to_registry(
    device_class: str,
    samples: list[dict],
    credentials: dict[str, str],
) -> None:
    """
    Replay historical samples to NavNet Registry via HTTP REST
    (MQTT doesn't support historic timestamps; use REST telemetry ingestion).
    """
    import httpx

    tb_url  = settings.tb_url.rstrip("/")
    devices = [
        (name, token)
        for name, token in credentials.items()
        if device_class in name.lower()
    ]

    if not devices:
        print(f"  No credentials found for device_class={device_class}")
        return

    device_name, token = devices[0]
    print(f"  Publishing {len(samples)} samples to {device_name} ...")

    # NavNet Registry REST telemetry ingestion with explicit timestamps
    with httpx.Client(timeout=10) as client:
        # Batch into chunks of 100
        chunk_size = 100
        for i in range(0, len(samples), chunk_size):
            chunk = samples[i : i + chunk_size]
            # TB batch format: [{ts, values: {...}}, ...]
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=DAYS)
            batch = []
            for j, s in enumerate(chunk):
                ts_ms = int((start + timedelta(seconds=(i + j) * INTERVAL_SECONDS)).timestamp() * 1000)
                batch.append({"ts": ts_ms, "values": s})

            resp = client.post(
                f"{tb_url}/api/v1/{token}/telemetry",
                json=batch,
            )
            if resp.status_code not in (200, 201):
                print(f"    Warning: HTTP {resp.status_code} on batch {i//chunk_size}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic baselines and train anomaly models")
    parser.add_argument(
        "--days",
        type=int,
        default=DAYS,
        help=f"Days of synthetic data to generate (default: {DAYS})",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish generated telemetry to NavNet Registry via REST",
    )
    parser.add_argument(
        "--credentials",
        default="credentials.csv",
        help="Path to credentials.csv (required if --publish)",
    )
    args = parser.parse_args()

    from services.anomaly import get_anomaly_service
    svc = get_anomaly_service()

    credentials: dict[str, str] = {}
    if args.publish:
        creds_path = Path(args.credentials)
        if not creds_path.exists():
            print(f"ERROR: credentials file not found: {creds_path}")
            sys.exit(1)
        with open(creds_path, newline="") as f:
            for row in csv.DictReader(f):
                credentials[row["name"]] = row["access_token"]
        print(f"Loaded {len(credentials)} device credentials")

    print(f"\nGenerating {args.days}-day synthetic baseline for {len(GENERATORS)} device classes")
    print(f"Interval: {INTERVAL_SECONDS}s, anomalies per class: {ANOMALIES_PER_CLASS}\n")

    for device_class, gen_fn in GENERATORS.items():
        print(f"[{device_class}]")
        samples = generate_dataset(device_class, args.days)
        total_steps = len(samples)
        anomaly_count = sum(
            1 for i, s in enumerate(samples)
            # Detect anomalies by checking extreme values per class
        )
        print(f"  Generated {total_steps} samples")

        # Train model
        svc.train(device_class, samples)
        model_path = Path(__file__).parent.parent / "fastapi" / "models" / f"isolation_forest_{device_class}.pkl"
        print(f"  ✓ Model saved: {model_path}")

        # Validate: score a known anomaly and confirm it triggers
        anomaly_sample = gen_fn(datetime.now(timezone.utc), anomaly=True)
        result = svc.score("validation", device_class, anomaly_sample)
        flag = "✓ DETECTED" if result.is_anomaly else "✗ missed"
        print(f"  Anomaly validation: score={result.score:.1f} sigma={result.sigma:.2f} → {flag}")

        # Normal sample sanity check
        normal_sample = gen_fn(datetime.now(timezone.utc), anomaly=False)
        result_normal = svc.score("validation", device_class, normal_sample)
        flag_n = "✓ OK (normal)" if not result_normal.is_anomaly else "✗ false positive"
        print(f"  Normal validation:  score={result_normal.score:.1f} sigma={result_normal.sigma:.2f} → {flag_n}")

        if args.publish:
            publish_to_registry(device_class, samples, credentials)

        print()

    print("[done] All models trained. Synthetic baseline ready.")
    print(f"       Model directory: {Path(__file__).parent.parent / 'fastapi' / 'models'}")


if __name__ == "__main__":
    main()
