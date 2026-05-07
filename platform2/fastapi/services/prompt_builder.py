"""
prompt_builder.py — Constructs the system prompt for Vantage Chat.

Injects device context and retrieved knowledge base documents.
The LLM is instructed to respond as an expert field engineer with a
specific, structured output format.
"""

from __future__ import annotations

import json
from langchain_core.documents import Document


def build_system_prompt(
    device_context: dict,
    rag_docs: list[Document],
    rag_pipeline: object | None = None,
) -> str:
    """
    Build the complete system prompt string.

    Args:
        device_context: Output of build_device_context().
        rag_docs: Retrieved Document objects from RAG pipeline.
        rag_pipeline: RAGPipeline instance for formatting docs (optional).
    """
    device_class = device_context.get("device_class", "general")
    device_name = device_context.get("device_name", "unknown device")

    # Format RAG context
    if rag_pipeline and rag_docs:
        rag_context = rag_pipeline.format_rag_context(rag_docs)
    elif rag_docs:
        sections = []
        for i, doc in enumerate(rag_docs, 1):
            src = doc.metadata.get("source", "unknown")
            sections.append(f"[{i}] ({src})\n{doc.page_content.strip()}")
        rag_context = "\n\n".join(sections)
    else:
        rag_context = "No relevant documentation found in the knowledge base."

    # Format device telemetry
    latest_tel = device_context.get("latest_telemetry", {})
    tel_lines = "\n".join(
        f"  {k}: {v}" for k, v in latest_tel.items()
    ) or "  (no telemetry available)"

    # Format 48hr trend summary
    summary = device_context.get("telemetry_48hr_summary", {})
    trend_lines = "\n".join(
        f"  {k}: min={v['min']} max={v['max']} mean={v['mean']} trend={v['trend']}"
        for k, v in summary.items()
    ) or "  (no history available)"

    # Format recent alarms
    alarms = device_context.get("recent_alarms", [])
    if alarms:
        alarm_lines = "\n".join(
            f"  [{a['severity']}] {a['type']} — {a['ts_human']} — {a['status']}"
            for a in alarms
        )
    else:
        alarm_lines = "  (no recent alarms)"

    # Extra attributes
    attrs = device_context.get("attributes", {})
    attr_lines = "\n".join(
        f"  {k}: {v}"
        for k, v in attrs.items()
        if k not in ("device_class", "location", "protocol")
    ) or "  (none)"

    errors = device_context.get("errors", [])
    data_quality = (
        "WARNING: Some device data unavailable — " + "; ".join(errors)
        if errors
        else "All device data retrieved successfully."
    )

    prompt = f"""You are an expert field operations engineer specialising in \
{device_class.upper()} systems for building management and network infrastructure.

You are assisting an operator who is looking at device **{device_name}** right now.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEVICE CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Device: {device_name}
Class:  {device_class}
Location: {device_context.get('location', 'unknown')}
Protocol: {device_context.get('protocol', 'unknown')}
Data quality: {data_quality}

Current readings:
{tel_lines}

48-hour trends:
{trend_lines}

Recent alarms:
{alarm_lines}

Additional attributes:
{attr_lines}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RETRIEVED KNOWLEDGE BASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{rag_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Answer ONLY from the device context and retrieved documents above.
   Do not invent values, part numbers, or procedures not present in the sources.

2. Be SPECIFIC. Include exact readings, thresholds, part numbers, stock codes,
   and time estimates whenever the context provides them.

3. Structure every response in this exact order:
   **Root cause** — one sentence identifying the most likely cause.
   **Immediate action** — what the operator should do RIGHT NOW (or "None required").
   **Permanent fix** — numbered step-by-step repair/resolution procedure.
   **Parts required** — list with stock codes if known; "None" if not applicable.
   **Estimated time** — labour hours to complete the permanent fix.

4. If a work order should be created (field technician visit needed), end your
   response with a JSON block in exactly this format — no other text after it:
   ```work_order
   {{
     "fault_description": "concise description of the fault",
     "steps": ["step 1", "step 2", "..."],
     "parts": [{{"name": "part name", "stock_code": "SKU or null", "qty": 1}}],
     "labour_hours": 2.5,
     "priority": 2
   }}
   ```
   Priority scale: 1=critical (safety/outage), 2=high, 3=medium, 4=low, 5=routine.

5. If you cannot answer from the provided context, say exactly:
   "I don't have enough information to diagnose this. To help further, I would need: [list]."
   Do NOT guess.
"""
    return prompt.strip()


def extract_work_order_json(llm_response: str) -> dict | None:
    """
    Parse the ```work_order ... ``` block from the LLM response.
    Returns the parsed dict or None if no block is present.
    """
    import re

    pattern = r"```work_order\s*(\{.*?\})\s*```"
    match = re.search(pattern, llm_response, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def strip_work_order_block(llm_response: str) -> str:
    """Remove the ```work_order block from the response for clean display."""
    import re

    return re.sub(r"\n*```work_order\s*\{.*?\}\s*```\s*$", "", llm_response, flags=re.DOTALL).rstrip()
