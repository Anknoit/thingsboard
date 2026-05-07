"""
Async SQLAlchemy engine, session factory, and ORM models for Platform 2.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


# ── Engine & session factory ─────────────────────────────────────────────────

engine = create_async_engine(
    settings.postgres_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        yield session


# ── ORM Base ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────────────────

class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String(255), nullable=False, index=True)
    device_name = Column(String(255), nullable=False)
    device_class = Column(String(64), nullable=False)
    fault_description = Column(Text, nullable=False)
    recommended_steps = Column(ARRAY(Text), nullable=False, server_default="{}")
    parts_required = Column(JSONB, nullable=True)
    estimated_labour_hours = Column(Float, nullable=True)
    priority = Column(Integer, nullable=False, default=3)  # 1=critical, 5=low
    status = Column(String(32), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    due_by = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String(255), nullable=True, index=True)
    event_type = Column(String(128), nullable=False)
    payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EquipmentHealth(Base):
    """TimescaleDB hypertable — partitioned on scored_at."""
    __tablename__ = "equipment_health"

    entity_id = Column(String(255), primary_key=True)
    scored_at = Column(DateTime(timezone=True), primary_key=True)
    health_score = Column(Float, nullable=False)
    failure_probability = Column(Float, nullable=False)
    features = Column(JSONB, nullable=True)
    model_version = Column(String(64), nullable=True)


class AnomalyScore(Base):
    """TimescaleDB hypertable — partitioned on scored_at."""
    __tablename__ = "anomaly_scores"

    entity_id = Column(String(255), primary_key=True)
    scored_at = Column(DateTime(timezone=True), primary_key=True)
    score = Column(Float, nullable=False)
    sigma = Column(Float, nullable=False)
    triggered = Column(Boolean, nullable=False, default=False)
    telemetry_snapshot = Column(JSONB, nullable=True)


# ── Hypertable setup helper ───────────────────────────────────────────────────

async def setup_hypertables() -> None:
    """
    Convert equipment_health and anomaly_scores to TimescaleDB hypertables.
    Safe to call multiple times (IF NOT EXISTS guard).
    """
    async with engine.begin() as conn:
        await conn.execute(text(
            "SELECT create_hypertable('equipment_health', 'scored_at', if_not_exists => TRUE);"
        ))
        await conn.execute(text(
            "SELECT create_hypertable('anomaly_scores', 'scored_at', if_not_exists => TRUE);"
        ))
