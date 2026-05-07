"""
POST /chat — Vantage Chat SSE streaming endpoint.

Flow:
  1. Rate-limit check (10 req/min per entity_id via Redis sliding window)
  2. Build device context (ThingsBoard data + widget context)
  3. Retrieve RAG documents from ChromaDB
  4. Build system prompt
  5. Stream LLM response token-by-token via SSE
  6. Parse ```work_order block → create work order in PostgreSQL
  7. Emit final SSE events (work_order, done)
  8. Audit log the full exchange
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from db.postgres import AsyncSessionLocal, AuditLog, WorkOrder
from models.schemas import ChatRequest
from services.context_builder import build_device_context
from services.llm_adapter import LLMProviderError, get_llm_adapter
from services.prompt_builder import (
    build_system_prompt,
    extract_work_order_json,
    strip_work_order_block,
)
from services.rag import get_rag_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW = 60  # seconds


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


# ── Rate limiting ─────────────────────────────────────────────────────────────

async def _check_rate_limit(entity_id: str) -> None:
    """
    Sliding window rate limit: 10 requests per minute per entity_id.
    Raises HTTP 429 if exceeded.
    """
    redis = await _get_redis()
    try:
        key = f"chat_rl:{entity_id}"
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW

        pipe = redis.pipeline()
        # Remove timestamps older than the window
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Count remaining
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Set TTL
        pipe.expire(key, RATE_LIMIT_WINDOW)
        results = await pipe.execute()

        count = results[1]
        if count >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {RATE_LIMIT_REQUESTS} requests per minute per device.",
            )
    finally:
        await redis.aclose()


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── Work order creation ───────────────────────────────────────────────────────

async def _create_work_order(wo_data: dict, entity_id: str, device_context: dict) -> str | None:
    """Persist a work order from the LLM's ```work_order block. Returns work order ID."""
    try:
        async with AsyncSessionLocal() as session:
            wo = WorkOrder(
                id=uuid.uuid4(),
                entity_id=entity_id,
                device_name=device_context.get("device_name", entity_id),
                device_class=device_context.get("device_class", "unknown"),
                fault_description=wo_data.get("fault_description", ""),
                recommended_steps=wo_data.get("steps", []),
                parts_required={"parts": wo_data.get("parts", [])},
                estimated_labour_hours=wo_data.get("labour_hours"),
                priority=int(wo_data.get("priority", 3)),
                status="open",
                created_at=datetime.now(timezone.utc),
            )
            session.add(wo)
            await session.commit()
            logger.info("Work order created: %s for entity %s", wo.id, entity_id)
            return str(wo.id)
    except Exception as exc:
        logger.exception("Failed to create work order: %s", exc)
        return None


# ── Audit logging ─────────────────────────────────────────────────────────────

async def _audit(
    entity_id: str,
    question: str,
    response: str,
    work_order_id: str | None,
    duration_ms: int,
    rag_sources: list[str],
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            log = AuditLog(
                id=uuid.uuid4(),
                entity_id=entity_id,
                event_type="chat_exchange",
                payload={
                    "question": question,
                    "response_length": len(response),
                    "work_order_id": work_order_id,
                    "duration_ms": duration_ms,
                    "rag_sources": rag_sources,
                },
                created_at=datetime.now(timezone.utc),
            )
            session.add(log)
            await session.commit()
    except Exception:
        logger.warning("Audit log write failed for entity %s", entity_id)


# ── Main SSE generator ────────────────────────────────────────────────────────

async def _chat_stream(body: ChatRequest) -> asyncio.AsyncGenerator[str, None]:
    t0 = time.monotonic()
    entity_id = body.entity_id
    full_response = ""
    work_order_id: str | None = None
    rag_sources: list[str] = []

    try:
        # 1. Device context
        widget_ctx = body.widget_context.model_dump() if body.widget_context else None
        device_context = await build_device_context(entity_id, widget_ctx)
        device_class = device_context.get("device_class", "unknown")

        # 2. RAG retrieval
        rag = get_rag_pipeline()
        docs = rag.retrieve_context(body.question, device_class=device_class, k=5)
        rag_sources = [d.metadata.get("source", "unknown") for d in docs]

        # 3. System prompt
        system_prompt = build_system_prompt(device_context, docs, rag)

        # 4. Stream LLM response
        llm = get_llm_adapter()
        messages = [{"role": "user", "content": body.question}]

        async for token in llm.stream_chat(system_prompt, messages):
            full_response += token
            yield _sse("token", {"content": token})

        # 5. Parse work order block
        wo_data = extract_work_order_json(full_response)
        clean_response = strip_work_order_block(full_response)

        # 6. Create work order if present
        if wo_data:
            work_order_id = await _create_work_order(wo_data, entity_id, device_context)
            if work_order_id:
                yield _sse("work_order", {
                    "id": work_order_id,
                    "data": wo_data,
                })

        # 7. Index this exchange as a fault_action for future RAG retrieval
        if wo_data and work_order_id:
            try:
                rag.add_fault_resolution(
                    entity_id=entity_id,
                    question=body.question,
                    resolution=clean_response,
                    device_class=device_class,
                )
            except Exception:
                pass  # Non-critical

        duration_ms = int((time.monotonic() - t0) * 1000)
        yield _sse("done", {"duration_ms": duration_ms})

        # 8. Audit log (fire and forget)
        asyncio.create_task(_audit(
            entity_id, body.question, clean_response,
            work_order_id, duration_ms, rag_sources,
        ))

    except LLMProviderError as exc:
        logger.error("LLM error for entity %s: %s", entity_id, exc)
        yield _sse("error", {"message": f"AI service error: {exc}"})

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Unexpected chat error for entity %s", entity_id)
        yield _sse("error", {"message": "An unexpected error occurred. Please try again."})


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    """
    Vantage Chat — streams AI-generated device diagnosis and resolution steps.

    Response is text/event-stream (SSE):
      data: {"type": "token",      "content": "..."}   — LLM token
      data: {"type": "work_order", "id": "...", "data": {...}}  — if WO created
      data: {"type": "done",       "duration_ms": N}
      data: {"type": "error",      "message": "..."}   — on failure
    """
    await _check_rate_limit(body.entity_id)

    return StreamingResponse(
        _chat_stream(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
