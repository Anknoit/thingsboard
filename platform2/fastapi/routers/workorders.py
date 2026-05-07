"""
Work order CRUD endpoints.

GET  /workorders?entity_id=&status=
POST /workorders
GET  /workorders/{id}
PATCH /workorders/{id}/status
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import AsyncSessionLocal, AuditLog, WorkOrder, get_db
from models.schemas import (
    STATUS_TRANSITIONS,
    VALID_STATUSES,
    WorkOrderCreate,
    WorkOrderList,
    WorkOrderResponse,
    WorkOrderStatusUpdate,
)

router = APIRouter(prefix="/workorders", tags=["workorders"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_work_order_or_404(wo_id: uuid.UUID, db: AsyncSession) -> WorkOrder:
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=404, detail=f"Work order {wo_id} not found")
    return wo


async def _write_audit(
    db: AsyncSession,
    entity_id: str,
    event_type: str,
    payload: dict,
) -> None:
    log = AuditLog(
        id=uuid.uuid4(),
        entity_id=entity_id,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=WorkOrderList)
async def list_work_orders(
    entity_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderList:
    """
    List work orders, optionally filtered by entity_id and/or status.
    Supports comma-separated status values: ?status=open,acknowledged,in_progress
    """
    stmt = select(WorkOrder)

    if entity_id:
        stmt = stmt.where(WorkOrder.entity_id == entity_id)

    if status:
        requested = {s.strip() for s in status.split(",")}
        invalid = requested - VALID_STATUSES
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid status values: {invalid}")
        stmt = stmt.where(WorkOrder.status.in_(requested))

    stmt = stmt.order_by(WorkOrder.priority.asc(), WorkOrder.created_at.desc())

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return WorkOrderList(
        items=[WorkOrderResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.post("", response_model=WorkOrderResponse, status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    wo = WorkOrder(
        id=uuid.uuid4(),
        entity_id=body.entity_id,
        device_name=body.device_name,
        device_class=body.device_class,
        fault_description=body.fault_description,
        recommended_steps=body.recommended_steps,
        parts_required=body.parts_required,
        estimated_labour_hours=body.estimated_labour_hours,
        priority=body.priority,
        status="open",
        created_at=datetime.now(timezone.utc),
        due_by=body.due_by,
    )
    db.add(wo)

    await _write_audit(db, body.entity_id, "work_order_created", {
        "work_order_id": str(wo.id),
        "fault_description": body.fault_description,
        "priority": body.priority,
    })

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.get("/{wo_id}", response_model=WorkOrderResponse)
async def get_work_order(
    wo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    wo = await _get_work_order_or_404(wo_id, db)
    return WorkOrderResponse.model_validate(wo)


@router.patch("/{wo_id}/status", response_model=WorkOrderResponse)
async def update_work_order_status(
    wo_id: uuid.UUID,
    body: WorkOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    wo = await _get_work_order_or_404(wo_id, db)

    allowed = STATUS_TRANSITIONS.get(wo.status, set())
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from '{wo.status}' to '{body.status}'. "
                   f"Allowed: {sorted(allowed) or 'none (terminal state)'}",
        )

    previous_status = wo.status
    wo.status = body.status
    if body.status == "closed":
        wo.closed_at = datetime.now(timezone.utc)

    await _write_audit(db, wo.entity_id, "work_order_status_changed", {
        "work_order_id": str(wo.id),
        "previous_status": previous_status,
        "new_status": body.status,
    })

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)
