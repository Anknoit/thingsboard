"""
schemas.py — All Pydantic v2 models for Platform 2.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Work Orders ───────────────────────────────────────────────────────────────

VALID_STATUSES = {"open", "acknowledged", "in_progress", "closed"}
STATUS_TRANSITIONS = {
    "open": {"acknowledged", "in_progress"},
    "acknowledged": {"in_progress"},
    "in_progress": {"closed"},
    "closed": set(),
}


class WorkOrderCreate(BaseModel):
    entity_id: str
    device_name: str
    device_class: str
    fault_description: str
    recommended_steps: list[str] = Field(default_factory=list)
    parts_required: dict[str, Any] | None = None
    estimated_labour_hours: float | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_by: datetime | None = None


class WorkOrderStatusUpdate(BaseModel):
    status: str

    def model_post_init(self, __context: Any) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")


class WorkOrderResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    device_name: str
    device_class: str
    fault_description: str
    recommended_steps: list[str]
    parts_required: dict[str, Any] | None
    estimated_labour_hours: float | None
    priority: int
    status: str
    created_at: datetime
    due_by: datetime | None
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class WorkOrderList(BaseModel):
    items: list[WorkOrderResponse]
    total: int


# ── Webhooks ──────────────────────────────────────────────────────────────────

class AlarmWebhookPayload(BaseModel):
    alarm_id: str
    entity_id: str
    entity_name: str
    alarm_type: str
    severity: str
    details: dict[str, Any] = Field(default_factory=dict)
    ts: int  # epoch ms


class CascadeAlarmEntry(BaseModel):
    alarm_id: str
    entity_id: str
    entity_name: str
    alarm_type: str
    severity: str
    ts: int


class CascadeWebhookPayload(BaseModel):
    """
    Sent by NavNet Registry when 3+ alarms fire within the cascade window.
    FastAPI also accumulates these from individual /webhook/alarm calls.
    """
    alarm_id: str
    entity_id: str
    entity_name: str
    alarm_type: str
    severity: str
    ts: int


class WebhookAck(BaseModel):
    status: str = "accepted"
    alarm_id: str | None = None


# ── Chat ──────────────────────────────────────────────────────────────────────

class WidgetContext(BaseModel):
    entity_name: str
    latest_telemetry: dict[str, Any] = Field(default_factory=dict)
    last_alarm: str | None = None


class ChatRequest(BaseModel):
    entity_id: str
    question: str = Field(..., min_length=3, max_length=2000)
    widget_context: WidgetContext | None = None


# ── Anomaly Detection ─────────────────────────────────────────────────────────

class AnomalyResult(BaseModel):
    entity_id: str
    device_class: str
    score: float = Field(ge=0, le=100)
    sigma: float
    is_anomaly: bool
    explanation: str
    features_used: dict[str, float]
    scored_at: datetime


# ── Predictive Maintenance ────────────────────────────────────────────────────

class PredictiveResult(BaseModel):
    entity_id: str
    device_class: str
    failure_probability: float = Field(ge=0.0, le=1.0)
    predicted_failure_window: str  # "24hr" | "48hr" | "72hr"
    contributing_features: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    scored_at: datetime


# ── GNN Root Cause ────────────────────────────────────────────────────────────

class RootCauseResult(BaseModel):
    root_cause_entity_id: str
    root_cause_device_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    blast_radius: list[str]  # list of entity_ids affected
    duration_ms: int  # time taken to compute


# ── Health ────────────────────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    status: str  # "ok" | "degraded" | "down"
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    services: dict[str, ServiceHealth]
    version: str = "1.0.0"


# ── Error responses ───────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    ts: datetime = Field(default_factory=datetime.utcnow)
