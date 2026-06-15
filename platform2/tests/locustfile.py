"""
locustfile.py — NavNet load test.

Tests three workload types that an operator generates:
  1. Chat queries  — POST /chat (SSE, consume full stream)
  2. Work order    — GET /workorders (list with filters)
  3. Alarm webhook — POST /webhook/alarm (rule chain simulation)

Usage:
    cd platform2/tests
    locust -f locustfile.py --host http://localhost:8000

    # Headless (CI):
    locust -f locustfile.py --host http://localhost:8000 \
        --headless -u 50 -r 5 --run-time 120s \
        --csv results/load_test

Targets (soft SLOs for demo):
  /chat       p95 < 8000ms  (SSE TTFB; full stream is slower)
  /workorders p95 < 400ms
  /webhook    p95 < 200ms
"""

from __future__ import annotations

import json
import random
import time
import uuid
from typing import Iterator

from locust import HttpUser, between, events, task

# ── Sample data ───────────────────────────────────────────────────────────────

# Subset of device IDs from devices.json — use real IDs after onboarding
SAMPLE_ENTITY_IDS = [
    "00000000-0001-0001-0001-000000000001",
    "00000000-0001-0001-0001-000000000002",
    "00000000-0001-0001-0001-000000000003",
    "00000000-0001-0001-0001-000000000004",
]

SAMPLE_QUESTIONS = [
    "Why is this device showing elevated temperature?",
    "What is the current operational status?",
    "Are there any anomalies in the last 24 hours?",
    "What maintenance is due for this equipment?",
    "Summarise recent alarms and recommend next steps.",
    "Is the power factor within acceptable limits?",
    "What caused the last alarm on this device?",
]

ALARM_TYPES = [
    "ANOMALY_DETECTED",
    "HIGH_TEMPERATURE",
    "LOW_POWER_FACTOR",
    "HIGH_VIBRATION",
    "NETWORK_DEGRADATION",
]

SEVERITIES = ["WARNING", "MAJOR", "CRITICAL"]

DEVICE_CLASSES = ["hvac", "energy", "network", "infra"]


# ── Operator user — realistic think-time ──────────────────────────────────────

class OperatorUser(HttpUser):
    """
    Simulates an operator browsing the NavNet dashboard.
    Ratio: 1 chat : 3 workorder lists : 2 webhook deliveries
    """

    wait_time = between(2, 8)   # seconds between tasks

    # ── Chat ──────────────────────────────────────────────────────────────────

    @task(1)
    def chat_query(self) -> None:
        entity_id = random.choice(SAMPLE_ENTITY_IDS)
        question  = random.choice(SAMPLE_QUESTIONS)

        payload = {
            "entity_id":    entity_id,
            "question":     question,
            "widget_context": {
                "device_name":  f"Device-{entity_id[:8]}",
                "device_class": random.choice(DEVICE_CLASSES),
            },
        }

        start = time.perf_counter()
        first_token_ms: float | None = None
        total_tokens = 0
        error: str | None = None

        try:
            with self.client.post(
                "/chat",
                json=payload,
                headers={"Accept": "text/event-stream"},
                stream=True,
                catch_response=True,
                name="/chat (SSE)",
            ) as resp:
                if resp.status_code != 200:
                    resp.failure(f"HTTP {resp.status_code}")
                    return

                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        if event.get("type") == "token":
                            total_tokens += 1
                            if first_token_ms is None:
                                first_token_ms = (time.perf_counter() - start) * 1000
                        elif event.get("type") == "done":
                            break
                        elif event.get("type") == "error":
                            error = event.get("message", "unknown error")
                            resp.failure(f"LLM error: {error}")
                            return

                resp.success()

        except Exception as exc:
            self.environment.events.request.fire(
                request_type="POST",
                name="/chat (SSE)",
                response_time=int((time.perf_counter() - start) * 1000),
                response_length=0,
                exception=exc,
                context={},
            )
            return

        # Report time-to-first-token as a separate custom metric
        if first_token_ms is not None:
            self.environment.events.request.fire(
                request_type="SSE-TTFB",
                name="/chat TTFB",
                response_time=int(first_token_ms),
                response_length=total_tokens,
                exception=None,
                context={},
            )

    # ── Work orders ───────────────────────────────────────────────────────────

    @task(3)
    def list_workorders(self) -> None:
        params: dict[str, str | int] = {
            "status":    random.choice(["open", "acknowledged", "open"]),
            "page":      1,
            "page_size": 20,
        }
        if random.random() < 0.4:
            params["entity_id"] = random.choice(SAMPLE_ENTITY_IDS)

        self.client.get(
            "/workorders",
            params=params,
            name="/workorders (list)",
        )

    @task(1)
    def get_workorder(self) -> None:
        # Uses a synthetic UUID — will 404 for missing WOs, which is expected
        wo_id = str(uuid.uuid4())
        with self.client.get(
            f"/workorders/{wo_id}",
            name="/workorders/{id}",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    # ── Webhook (simulates NavNet Registry rule chain) ────────────────────────────

    @task(2)
    def alarm_webhook(self) -> None:
        payload = {
            "alarm_id":    str(uuid.uuid4()),
            "entity_id":   random.choice(SAMPLE_ENTITY_IDS),
            "entity_name": f"Device-{random.randint(1, 16):02d}",
            "alarm_type":  random.choice(ALARM_TYPES),
            "severity":    random.choice(SEVERITIES),
            "status":      "ACTIVE_UNACK",
            "ts":          int(time.time() * 1000),
        }
        self.client.post(
            "/webhook/alarm",
            json=payload,
            name="/webhook/alarm",
        )

    @task(1)
    def cascade_webhook(self) -> None:
        payload = {
            "alarm_id":    str(uuid.uuid4()),
            "entity_id":   random.choice(SAMPLE_ENTITY_IDS),
            "entity_name": f"Device-{random.randint(1, 16):02d}",
            "alarm_type":  random.choice(ALARM_TYPES),
            "alarm_count": random.randint(3, 8),
        }
        self.client.post(
            "/webhook/cascade",
            json=payload,
            name="/webhook/cascade",
        )

    # ── Health probe ──────────────────────────────────────────────────────────

    @task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")


# ── Alarm storm user — for stress testing ─────────────────────────────────────

class AlarmStormUser(HttpUser):
    """
    Simulates a burst of alarms (e.g. after a power event or network failure).
    Use sparingly — combine with OperatorUser for realistic load.
    """

    wait_time = between(0.1, 0.5)

    @task
    def fire_alarm(self) -> None:
        payload = {
            "alarm_id":    str(uuid.uuid4()),
            "entity_id":   random.choice(SAMPLE_ENTITY_IDS),
            "entity_name": f"Device-{random.randint(1, 16):02d}",
            "alarm_type":  random.choice(ALARM_TYPES),
            "severity":    random.choice(SEVERITIES),
            "status":      "ACTIVE_UNACK",
            "ts":          int(time.time() * 1000),
        }
        self.client.post(
            "/webhook/alarm",
            json=payload,
            name="/webhook/alarm (storm)",
        )


# ── Custom stats output on test completion ────────────────────────────────────

@events.quitting.add_listener
def on_quitting(environment, **kwargs) -> None:
    stats = environment.stats

    print("\n" + "=" * 60)
    print("NavNet Load Test — Summary")
    print("=" * 60)

    key_endpoints = ["/chat (SSE)", "/workorders (list)", "/webhook/alarm", "/health"]
    for name in key_endpoints:
        entry = stats.get(name, "POST") or stats.get(name, "GET")
        if entry and entry.num_requests > 0:
            print(
                f"  {name:<28} "
                f"reqs={entry.num_requests:>5}  "
                f"fail={entry.num_failures:>3}  "
                f"p50={entry.get_response_time_percentile(0.50):>6.0f}ms  "
                f"p95={entry.get_response_time_percentile(0.95):>6.0f}ms"
            )

    print("=" * 60)
    fail_ratio = stats.total.fail_ratio
    if fail_ratio > 0.05:
        print(f"WARNING: failure rate {fail_ratio:.1%} exceeds 5% threshold")
    else:
        print(f"OK: failure rate {fail_ratio:.1%}")
    print()
