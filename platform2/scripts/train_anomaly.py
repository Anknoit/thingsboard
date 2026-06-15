"""
train_anomaly.py — Train Isolation Forest models on historical NavNet Registry data.

Usage:
    python train_anomaly.py --device-class hvac --days 30
    python train_anomaly.py --device-class network --days 14
    python train_anomaly.py --all --days 30   # train all device classes
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Allow running from repo root or scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "fastapi"))

from config import settings  # noqa: E402

DEVICE_CLASSES = ["hvac", "energy", "network", "infra"]


def fetch_devices_by_class(tb, device_class: str) -> list[dict]:
    """Return all NavNet Registry devices matching device_class shared attribute."""
    import httpx

    # TB doesn't filter by attribute in /api/tenant/devices directly.
    # We page through all devices and filter by the shared attribute.
    print(f"  Fetching devices with device_class={device_class} ...")
    devices = []
    page = 0
    page_size = 100

    while True:
        resp = tb.client.get(
            f"{tb.base_url}/api/tenant/devices",
            params={"pageSize": page_size, "page": page},
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("data", [])

        for device in batch:
            did = device["id"]["id"]
            try:
                attrs_resp = tb.client.get(
                    f"{tb.base_url}/api/plugins/telemetry/DEVICE/{did}/values/attributes/SHARED_SCOPE"
                )
                attrs = {a["key"]: a["value"] for a in attrs_resp.json()}
                if attrs.get("device_class") == device_class:
                    device["_attrs"] = attrs
                    devices.append(device)
            except Exception:
                pass

        if data.get("hasNext"):
            page += 1
        else:
            break

    print(f"  Found {len(devices)} device(s) with device_class={device_class}")
    return devices


def fetch_telemetry_for_device(tb, device_id: str, days: int) -> list[dict]:
    """Fetch up to 30 days of telemetry, return list of flat dicts."""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 86400 * 1000

    resp = tb.client.get(
        f"{tb.base_url}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
        params={"startTs": start_ms, "endTs": now_ms, "limit": 5000, "agg": "NONE"},
    )
    if resp.status_code != 200:
        return []

    data = resp.json()
    if not data:
        return []

    # Pivot from {key: [{ts, value}]} to [{ts, key: value, ...}]
    ts_map: dict[int, dict] = {}
    for key, readings in data.items():
        for r in readings:
            ts = r["ts"]
            ts_map.setdefault(ts, {})
            try:
                ts_map[ts][key] = float(r["value"])
            except (TypeError, ValueError):
                pass

    return list(ts_map.values())


def train_class(device_class: str, days: int) -> None:
    import httpx
    from services.anomaly import get_anomaly_service

    print(f"\n{'='*55}")
    print(f"Training: device_class={device_class}, days={days}")
    print(f"{'='*55}")

    # Create a simple synchronous TB client for the script
    class SyncTB:
        def __init__(self):
            self.base_url = settings.tb_url.rstrip("/")
            self.client = httpx.Client(timeout=30)
            resp = self.client.post(
                f"{self.base_url}/api/auth/login",
                json={"username": settings.tb_admin_user, "password": settings.tb_admin_password},
            )
            resp.raise_for_status()
            token = resp.json()["token"]
            self.client.headers["X-Authorization"] = f"Bearer {token}"

    tb = SyncTB()

    devices = fetch_devices_by_class(tb, device_class)
    if not devices:
        print(f"  No devices found for device_class={device_class}. Nothing to train.")
        return

    all_samples: list[dict] = []
    for device in devices:
        did  = device["id"]["id"]
        name = device.get("name", did)
        samples = fetch_telemetry_for_device(tb, did, days)
        print(f"    {name}: {len(samples)} samples")
        all_samples.extend(samples)

    if not all_samples:
        print(f"  No telemetry collected for device_class={device_class}. Aborting.")
        return

    print(f"\n  Total training samples: {len(all_samples)}")
    print(f"  Training Isolation Forest ...")

    svc = get_anomaly_service()
    svc.train(device_class, all_samples)

    model_path = os.path.join(
        Path(__file__).parent.parent / "fastapi" / "models",
        f"isolation_forest_{device_class}.pkl",
    )
    print(f"  ✓ Model saved to {model_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train Isolation Forest anomaly models from NavNet Registry telemetry"
    )
    parser.add_argument(
        "--device-class",
        choices=DEVICE_CLASSES,
        help="Device class to train",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Train all device classes",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=settings.anomaly_baseline_days,
        help=f"Days of historical data to use (default: {settings.anomaly_baseline_days})",
    )
    args = parser.parse_args()

    if not args.device_class and not args.all:
        parser.error("Provide --device-class <class> or --all")

    classes = DEVICE_CLASSES if args.all else [args.device_class]

    for dc in classes:
        train_class(dc, args.days)

    print("\n[done] Training complete.")


if __name__ == "__main__":
    main()
