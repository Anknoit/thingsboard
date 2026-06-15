"""
fault_injector.py — NavNet demo fault injection server.

Runs on port 8001 (separate from the main FastAPI on 8000).
Used exclusively in demo / development mode (docker compose --profile demo).

Endpoints:
  POST /inject/{scenario}     Load scenario and apply overrides to simulator
  GET  /scenarios             List available scenarios
  GET  /status                Show currently active injections
  POST /reset                 Clear all active injections
  POST /reset/{device_name}   Clear injection for a specific device

The injector writes into mqtt_sim._INJECTIONS so the live simulator loop
picks up overrides on the next publish cycle without restarting.

When run as a standalone container alongside mqtt_sim.py, it communicates
via a shared named volume that exposes a JSON state file. The simulator
reads this file at each publish cycle instead.

IMPORTANT: This service must never be started in production.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vantage.fault_injector")

SCENARIOS_DIR  = Path(__file__).parent / "scenarios"
STATE_FILE     = Path(os.getenv("INJECTOR_STATE_FILE", "/tmp/vantage_injections.json"))

app = FastAPI(
    title="NavNet — Fault Injector",
    version="1.0.0",
    description="Demo fault injection API. For development and demo use only.",
    docs_url="/docs",
)


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict[str, dict]:
    """Load active injections from state file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, dict]) -> None:
    """Persist active injections to state file (simulator reads this)."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _active_injections() -> dict[str, dict]:
    """Return only injections that haven't expired yet."""
    now   = time.time()
    state = _load_state()
    active = {
        name: inj
        for name, inj in state.items()
        if inj.get("__until", 0) > now
    }
    if len(active) != len(state):
        _save_state(active)
    return active


# ── Scenario loader ───────────────────────────────────────────────────────────

def _list_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            scenarios.append({
                "name":        path.stem,
                "description": data.get("description", ""),
                "devices":     data.get("target_devices", []),
                "duration_s":  data.get("duration_seconds", 300),
            })
        except Exception as exc:
            logger.warning("Could not parse scenario %s: %s", path.name, exc)
    return scenarios


def _load_scenario(name: str) -> dict:
    path = SCENARIOS_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{name}' not found. Available: {[s['name'] for s in _list_scenarios()]}",
        )
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse scenario '{name}': {exc}",
        )


# ── Request/response models ───────────────────────────────────────────────────

class InjectionResponse(BaseModel):
    status:          str
    scenario:        str
    devices_injected: list[str]
    expires_at:      str
    description:     str


class StatusResponse(BaseModel):
    active_injections: int
    injections:        dict[str, Any]
    server_time:       str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post(
    "/inject/{scenario}",
    response_model=InjectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Inject a fault scenario",
    description=(
        "Activates the named fault scenario. The simulator will apply the "
        "telemetry overrides on the next publish cycle for each target device."
    ),
)
async def inject_scenario(scenario: str) -> InjectionResponse:
    data     = _load_scenario(scenario)
    targets  = data.get("target_devices", [])
    duration = float(data.get("duration_seconds", 300))
    until    = time.time() + duration
    until_dt = datetime.fromtimestamp(until, tz=timezone.utc).isoformat()
    steps    = data.get("steps", [])

    if not targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Scenario has no target_devices defined.",
        )

    state = _active_injections()

    # Apply step 0 overrides immediately (progressive steps need scheduler — not in MVP)
    active_step = steps[0] if steps else {}
    device_overrides: dict[str, dict] = active_step.get("device_overrides", {})

    # If no per-step overrides, fall back to flat telemetry_overrides
    if not device_overrides:
        flat = data.get("telemetry_overrides", {})
        device_overrides = {t: flat for t in targets}

    injected = []
    for device_name in targets:
        overrides = device_overrides.get(device_name, {})
        state[device_name] = {
            **overrides,
            "__until":   until,
            "__scenario": scenario,
        }
        injected.append(device_name)
        logger.info(
            "injection applied: device=%s scenario=%s duration=%.0fs keys=%s",
            device_name, scenario, duration, list(overrides.keys()),
        )

    _save_state(state)

    return InjectionResponse(
        status="injected",
        scenario=scenario,
        devices_injected=injected,
        expires_at=until_dt,
        description=data.get("description", ""),
    )


@app.get(
    "/scenarios",
    summary="List available fault scenarios",
)
async def list_scenarios() -> dict:
    return {
        "scenarios": _list_scenarios(),
        "scenarios_dir": str(SCENARIOS_DIR),
    }


@app.get(
    "/status",
    response_model=StatusResponse,
    summary="Show active injections",
)
async def get_status() -> StatusResponse:
    active = _active_injections()
    # Convert __until epoch to human-readable
    display = {}
    for device, inj in active.items():
        display[device] = {
            k: (
                datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
                if k == "__until" else v
            )
            for k, v in inj.items()
        }
    return StatusResponse(
        active_injections=len(active),
        injections=display,
        server_time=datetime.now(timezone.utc).isoformat(),
    )


@app.post(
    "/reset",
    summary="Clear all active fault injections",
)
async def reset_all() -> dict:
    state = _load_state()
    count = len(state)
    _save_state({})
    logger.info("reset: cleared %d injection(s)", count)
    return {"status": "cleared", "injections_removed": count}


@app.post(
    "/reset/{device_name}",
    summary="Clear injection for a specific device",
)
async def reset_device(device_name: str) -> dict:
    state = _load_state()
    if device_name not in state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active injection for device '{device_name}'.",
        )
    state.pop(device_name)
    _save_state(state)
    logger.info("reset: cleared injection for %s", device_name)
    return {"status": "cleared", "device": device_name}


@app.get("/health", summary="Fault injector health check")
async def health() -> dict:
    return {
        "status": "ok",
        "active_injections": len(_active_injections()),
        "scenarios_available": len(_list_scenarios()),
        "state_file": str(STATE_FILE),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fault_injector:app",
        host="0.0.0.0",
        port=int(os.getenv("INJECTOR_PORT", "8001")),
        reload=False,
        log_level="info",
    )
