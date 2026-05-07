"""
mqtt_sim.py — Vantage NMS demo MQTT telemetry simulator.

Publishes realistic telemetry for 16 devices to ThingsBoard via MQTT.
Each device runs on its own asyncio loop at its natural publish interval.
The fault_injector can override any device's telemetry via a shared dict.

Usage:
    python mqtt_sim.py
    python mqtt_sim.py --host tb.example.com --port 1883 --interval 30

Environment variables (also accepted):
    TB_MQTT_HOST    ThingsBoard MQTT broker host (default: localhost)
    TB_MQTT_PORT    1883 or 8883 for TLS (default: 1883)
    SIM_INTERVAL    Base publish interval in seconds (default: 30)
    SIM_DEVICES     Path to devices.json (default: devices.json)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("vantage.simulator")

# ── Shared injection state (written by fault_injector, read by generators) ───
# Dict of device_name → {telemetry_key: override_value, "__until": epoch_float}
_INJECTIONS: dict[str, dict[str, Any]] = {}
_INJECTION_LOCK = asyncio.Lock()


# ── Telemetry generators ──────────────────────────────────────────────────────

def _tod(ts: datetime) -> float:
    """Sinusoidal time-of-day factor: 0.0 at midnight → 1.0 at noon."""
    h = ts.hour + ts.minute / 60.0
    return (math.sin(math.pi * (h - 6) / 12) + 1) / 2


def _biz(ts: datetime) -> float:
    return 1.0 if (8 <= ts.hour < 18 and ts.weekday() < 5) else 0.1


def gen_hvac(ts: datetime) -> dict[str, float]:
    tod = _tod(ts)
    biz = _biz(ts)
    return {
        "temperature":        round(18 + 6 * tod + random.gauss(0, 0.4), 2),
        "humidity":           round(45 + 15 * (1 - tod) + random.gauss(0, 1.5), 1),
        "power_consumption":  round(2 + 3 * tod + random.gauss(0, 0.15), 3),
        "fan_speed":          round(800 + 600 * tod + random.gauss(0, 30), 0),
        "co2_level":          round(400 + 400 * biz + random.gauss(0, 20), 0),
        "vibration_rms":      round(0.5 + 0.3 * tod + random.gauss(0, 0.05), 3),
        "current_draw":       round(4.0 + 1.5 * tod + random.gauss(0, 0.1), 2),
        "error_count":        max(0, round(random.gauss(0.2, 0.2), 0)),
    }


def gen_energy(ts: datetime) -> dict[str, float]:
    biz = _biz(ts)
    active_power   = 10 + 40 * biz + random.gauss(0, 1.5)
    reactive_power = active_power * 0.3 + random.gauss(0, 0.5)
    current        = active_power / 0.4 + random.gauss(0, 0.5)
    return {
        "active_power":   round(active_power, 2),
        "reactive_power": round(reactive_power, 2),
        "current":        round(current, 2),
        "voltage":        round(400 + random.gauss(0, 2), 1),
        "power_factor":   round(min(1.0, max(0.5, 0.92 + random.gauss(0, 0.02))), 3),
        "error_count":    max(0, round(random.gauss(0.1, 0.1), 0)),
    }


def gen_network(ts: datetime) -> dict[str, float]:
    biz = _biz(ts)
    rx  = (1_000_000 + 99_000_000 * biz) * random.uniform(0.7, 1.3)
    return {
        "rx_bytes":    round(rx, 0),
        "tx_bytes":    round(rx * random.uniform(0.3, 0.7), 0),
        "error_rate":  round(max(0, random.gauss(0.02, 0.01)), 4),
        "latency":     round(max(1, random.gauss(5, 1.5)), 2),
        "packet_loss": round(max(0, random.gauss(0.01, 0.005)), 4),
        "error_count": max(0, round(random.gauss(0, 0.3), 0)),
    }


def gen_infra(ts: datetime) -> dict[str, float]:
    biz = _biz(ts)
    cpu = min(99, max(5, 20 + 40 * biz + random.gauss(0, 5)))
    return {
        "cpu_usage":    round(cpu, 1),
        "memory_usage": round(min(99, max(5, 45 + 20 * biz + random.gauss(0, 3))), 1),
        "disk_io":      round(max(0, 10 + 50 * biz + random.gauss(0, 5)), 1),
        "temperature":  round(45 + 10 * (cpu / 80) + random.gauss(0, 1.5), 1),
        "error_count":  max(0, round(random.gauss(0, 0.5), 0)),
    }


def gen_occupancy(ts: datetime) -> dict[str, float]:
    biz = _biz(ts)
    return {
        "occupancy_count": max(0, round(50 * biz + random.gauss(0, 5), 0)),
        "door_events":     max(0, round(20 * biz + random.gauss(0, 3), 0)),
    }


GENERATORS = {
    "hvac":       gen_hvac,
    "energy":     gen_energy,
    "network":    gen_network,
    "infra":      gen_infra,
    "occupancy":  gen_occupancy,
}


# ── MQTT client wrapper ───────────────────────────────────────────────────────

class DevicePublisher:
    """
    Manages a single paho-mqtt client for one device.
    Publishes telemetry to v1/devices/me/telemetry using the device access token.
    """

    TOPIC = "v1/devices/me/telemetry"

    def __init__(self, device: dict, host: str, port: int) -> None:
        self.device  = device
        self.name    = device["name"]
        self.dc      = device["device_class"]
        self.token   = device["access_token"]
        self.host    = host
        self.port    = port
        self._client = mqtt.Client(
            client_id=f"sim-{self.name}",
            clean_session=True,
        )
        self._client.username_pw_set(self.token)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._connected = False

    def connect(self) -> None:
        self._client.connect(self.host, self.port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish(self, payload: dict) -> None:
        if not self._connected:
            return
        self._client.publish(self.TOPIC, json.dumps(payload), qos=1)

    def _on_connect(self, client, userdata, flags, rc: int) -> None:
        if rc == 0:
            self._connected = True
            logger.info("connected: %s", self.name)
        else:
            logger.warning("connect failed: %s rc=%d", self.name, rc)

    def _on_disconnect(self, client, userdata, rc: int) -> None:
        self._connected = False
        if rc != 0:
            logger.warning("disconnected: %s rc=%d", self.name, rc)


# ── Per-device async loop ─────────────────────────────────────────────────────

async def device_loop(
    device: dict,
    publisher: DevicePublisher,
    interval: float,
    stop_event: asyncio.Event,
) -> None:
    """
    Publishes telemetry every `interval` seconds.
    Checks _INJECTIONS for any active overrides and merges them into the payload.
    """
    gen = GENERATORS.get(device["device_class"], gen_hvac)
    name = device["name"]

    # Stagger startup to avoid thundering herd
    await asyncio.sleep(random.uniform(0, min(interval, 5)))

    while not stop_event.is_set():
        try:
            now     = datetime.now(timezone.utc)
            payload = gen(now)

            # Apply active injection overrides
            async with _INJECTION_LOCK:
                inj = _INJECTIONS.get(name)
                if inj:
                    if time.time() < inj.get("__until", 0):
                        overrides = {k: v for k, v in inj.items() if not k.startswith("__")}
                        payload.update(overrides)
                        logger.debug("injection active: %s → %s", name, list(overrides.keys()))
                    else:
                        # Injection expired
                        _INJECTIONS.pop(name, None)
                        logger.info("injection expired: %s", name)

            publisher.publish(payload)
            logger.debug("published: %s %s", name, payload)

        except Exception as exc:
            logger.warning("publish error: %s — %s", name, exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break  # stop_event was set
        except asyncio.TimeoutError:
            pass   # normal — continue loop


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_simulator(host: str, port: int, interval: float, devices_path: Path) -> None:
    with open(devices_path) as f:
        devices: list[dict] = json.load(f)

    logger.info(
        "Starting Vantage NMS simulator — %d devices, interval=%.0fs, broker=%s:%d",
        len(devices), interval, host, port,
    )

    publishers = []
    for device in devices:
        pub = DevicePublisher(device, host, port)
        pub.connect()
        publishers.append((device, pub))

    # Give MQTT time to connect
    await asyncio.sleep(2)

    stop_event = asyncio.Event()

    # Handle SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(
            device_loop(device, pub, interval, stop_event),
            name=f"sim-{device['name']}",
        )
        for device, pub in publishers
    ]

    logger.info("Simulator running — Ctrl+C to stop")
    await asyncio.gather(*tasks, return_exceptions=True)

    for _, pub in publishers:
        pub.disconnect()

    logger.info("Simulator stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vantage NMS MQTT simulator")
    parser.add_argument("--host",     default=os.getenv("TB_MQTT_HOST", "localhost"))
    parser.add_argument("--port",     type=int, default=int(os.getenv("TB_MQTT_PORT", "1883")))
    parser.add_argument("--interval", type=float, default=float(os.getenv("SIM_INTERVAL", "30")))
    parser.add_argument(
        "--devices",
        type=Path,
        default=Path(os.getenv("SIM_DEVICES", Path(__file__).parent / "devices.json")),
    )
    args = parser.parse_args()
    asyncio.run(run_simulator(args.host, args.port, args.interval, args.devices))


if __name__ == "__main__":
    main()
