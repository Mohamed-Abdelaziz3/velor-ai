"""Small, sanitized telemetry layer for pilot reliability, quality, and cost."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Iterable

from sqlalchemy.orm import Session

from database import SystemEvent


PILOT_EVENT_NAMES = {
    "merchant_onboarding_started",
    "merchant_onboarding_completed",
    "catalog_first_valid_product",
    "first_public_conversation",
    "first_owner_action",
    "customer_reply_generated",
    "owner_draft_used",
    "owner_takeover",
    "follow_up_created",
    "follow_up_completed",
    "purchase_advancement_detected",
    "purchase_handoff_started",
    "purchase_handoff_completed",
    "unsupported_information_flagged",
    "merchant_corrected_response",
    "conversation_resolved",
    "opportunity_shown",
    "opportunity_opened",
    "owner_action_started",
    "suggestion_generated",
    "suggestion_inserted",
    "suggestion_sent",
    "suggestion_dismissed",
    "suggestion_stale_blocked",
    "follow_up_dismissed",
    "follow_up_snoozed",
    "follow_up_reactivated",
    "follow_up_cancelled",
    "follow_up_superseded",
    "knowledge_gap_resolved",
    "subsequent_progress_observed",
    # Reserved for verified provider integrations. Client telemetry rejects them.
    "confirmed_order",
    "paid",
}

CLIENT_EVENT_NAMES = {
    "opportunity_shown",
    "opportunity_opened",
    "owner_action_started",
    "suggestion_inserted",
}

ALLOWED_TRACE_KEYS = {
    "request_id",
    "source_message_id",
    "response_engine_version",
    "response_path",
    "response_plan_type",
    "model_provider",
    "model_name",
    "provider_result",
    "verifier_result",
    "fallback_reason",
    "latency_ms",
    "provider_latency_ms",
    "input_token_estimate",
    "output_token_estimate",
    "input_tokens_estimate",
    "output_tokens_estimate",
    "retry_count",
    "model_call_count",
    "commercial_persistence_result",
    "sse_emission",
    "error_category",
    "semantic_fulfillment",
}

ALLOWED_EVENT_METADATA = {
    "channel",
    "response_path",
    "plan_type",
    "fallback_reason",
    "outcome",
    "estimated",
    "source_message_id",
    "source_message_internal_id",
    "lead_id",
    "suggestion_id",
    "task_id",
    "queue_item_id",
    "variant_style",
    "edited",
    "surface",
    "status",
    "reason_code",
    "due_at",
}


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:160]


def _safe_semantic_fulfillment(value: Any) -> dict[str, Any]:
    """Keep only the compact, non-conversational semantic audit contract.

    This record is deliberately useful for acceptance evidence without storing
    customer wording, assistant prose, identifiers, prompts, or model output.
    """
    if not isinstance(value, dict):
        return {}
    scalar_keys = {
        "schema", "capability", "obligation_type", "target", "planned_action",
        "verifier_outcome", "verifier_passed",
    }
    list_keys = {"requested_slots", "facts", "unknown_slots"}
    safe: dict[str, Any] = {}
    for key in scalar_keys:
        if key in value:
            safe[key] = _safe_scalar(value[key])
    for key in list_keys:
        if isinstance(value.get(key), list):
            safe[key] = [_safe_scalar(item) for item in value[key][:12]]
    return safe


def _filtered(values: dict[str, Any] | None, allowed: Iterable[str]) -> dict[str, Any]:
    source = values or {}
    return {
        key: (_safe_semantic_fulfillment(source[key]) if key == "semantic_fulfillment" else _safe_scalar(source[key]))
        for key in allowed
        if key in source
    }


def record_pilot_event(
    db: Session,
    *,
    event_name: str,
    company_id: str,
    actor_type: str,
    entity_id: str | int,
    source: str,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    commit: bool = True,
) -> SystemEvent:
    if event_name not in PILOT_EVENT_NAMES:
        raise ValueError("unsupported_pilot_event")
    if event_name in {"confirmed_order", "paid"}:
        from services.trusted_outcome_contract import is_trusted_outcome_provenance

        if not is_trusted_outcome_provenance(source):
            raise ValueError("trusted_provider_outcome_required")
    event_type = f"pilot.{event_name}"
    scoped_entity = str(entity_id)[:128]
    safe_key = str(idempotency_key)[:160] if idempotency_key else None
    existing_query = db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == event_type,
    )
    existing = (
        existing_query.filter(SystemEvent.idempotency_key == safe_key).first()
        if safe_key
        else existing_query.filter(SystemEvent.entity_id == scoped_entity).first()
    )
    if existing:
        return existing
    payload = {
        "event": event_name,
        "company_id": company_id,
        "actor_type": actor_type[:30],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entity_id": scoped_entity,
        "source": source[:80],
        "metadata": _filtered(metadata, ALLOWED_EVENT_METADATA),
    }
    row = SystemEvent(
        company_id=company_id,
        event_type=event_type,
        entity_id=scoped_entity,
        idempotency_key=safe_key,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def _validate_client_reference(db: Session, company_id: str, event_name: str, metadata: dict[str, Any]) -> None:
    from database import CommercialEvent, FollowUpTask, Lead, WorkspaceSuggestedReply

    lead_id = metadata.get("lead_id")
    lead = None
    if lead_id is not None:
        lead = db.query(Lead).filter(
            Lead.id == int(lead_id),
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
        ).first()
        if not lead:
            raise ValueError("invalid_telemetry_lead")

    suggestion_id = metadata.get("suggestion_id")
    if suggestion_id is not None:
        suggestion = db.query(WorkspaceSuggestedReply).filter(
            WorkspaceSuggestedReply.id == int(suggestion_id),
            WorkspaceSuggestedReply.company_id == company_id,
        ).first()
        if not suggestion or (lead_id is not None and suggestion.lead_id != int(lead_id)):
            raise ValueError("invalid_telemetry_suggestion")
        supplied_source = metadata.get("source_message_internal_id")
        if supplied_source and supplied_source != suggestion.source_message_internal_id:
            raise ValueError("invalid_telemetry_source_message")
    elif event_name == "suggestion_inserted":
        raise ValueError("suggestion_reference_required")

    task_id = metadata.get("task_id")
    if task_id is not None:
        task = db.query(FollowUpTask).filter(
            FollowUpTask.id == int(task_id),
            FollowUpTask.company_id == company_id,
        ).first()
        if not task or (lead_id is not None and task.lead_id != int(lead_id)):
            raise ValueError("invalid_telemetry_follow_up")

    queue_item_id = metadata.get("queue_item_id")
    if event_name in {"opportunity_shown", "opportunity_opened", "owner_action_started"}:
        if not queue_item_id or lead is None:
            raise ValueError("queue_reference_required")
        from services.owner_attention_projection_service import get_commercial_queue

        current_ids = {
            str(item.get("queue_item_id") or item.get("id"))
            for item in get_commercial_queue(db, company_id, limit=100).get("items", [])
        }
        if str(queue_item_id) not in current_ids:
            # The analytical queue retains source-linked commercial-event rows
            # beyond the compact owner queue. Validate that exact deterministic ID.
            parts = str(queue_item_id).split(":", 3)
            valid_analytical = False
            if len(parts) == 4 and parts[0] == "commercial-opportunity" and parts[1].isdigit():
                event_row = db.query(CommercialEvent.id).filter(
                    CommercialEvent.company_id == company_id,
                    CommercialEvent.lead_id == int(parts[1]),
                    CommercialEvent.event_type == parts[2],
                    CommercialEvent.source_message_internal_id == parts[3],
                ).first()
                valid_analytical = bool(event_row and int(parts[1]) == int(lead_id))
            if not valid_analytical:
                raise ValueError("invalid_telemetry_queue_item")


def record_client_product_events(
    db: Session,
    *,
    company_id: str,
    events: list[dict[str, Any]],
) -> list[SystemEvent]:
    """Validate and persist a bounded client batch with server timestamps."""
    if not events or len(events) > 50:
        raise ValueError("invalid_telemetry_batch")
    validated: list[tuple[str, str, dict[str, Any]]] = []
    for event in events:
        event_name = str(event.get("event_name") or "")
        client_event_id = str(event.get("client_event_id") or "").strip()
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        if event_name not in CLIENT_EVENT_NAMES:
            raise ValueError("unsupported_client_event")
        if not client_event_id or len(client_event_id) > 160:
            raise ValueError("client_event_id_required")
        _validate_client_reference(db, company_id, event_name, metadata)
        validated.append((event_name, client_event_id, metadata))

    # Validate the complete batch before adding rows. A bad reference therefore
    # cannot leave earlier events pending in a caller-owned SQLAlchemy session.
    rows: list[SystemEvent] = []
    for event_name, client_event_id, metadata in validated:
        entity_id = (
            metadata.get("queue_item_id")
            or metadata.get("suggestion_id")
            or metadata.get("task_id")
            or metadata.get("lead_id")
        )
        rows.append(record_pilot_event(
            db,
            event_name=event_name,
            company_id=company_id,
            actor_type="owner",
            entity_id=entity_id,
            source="owner_console",
            metadata=metadata,
            idempotency_key=f"client:{client_event_id}",
            commit=False,
        ))
    db.commit()
    return rows


def record_ai_trace(
    db: Session,
    *,
    company_id: str,
    lead_id: int | None,
    trace: dict[str, Any],
    commit: bool = True,
) -> SystemEvent:
    safe_trace = _filtered(trace, ALLOWED_TRACE_KEYS)
    source_message_id = safe_trace.get("source_message_id") or trace.get("source_message_id") or "unknown"
    entity_id = f"{lead_id or 'none'}:{source_message_id}"[:128]
    existing = db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "telemetry.ai_response",
        SystemEvent.entity_id == entity_id,
    ).first()
    if existing:
        return existing

    input_tokens = int(safe_trace.get("input_token_estimate") or safe_trace.get("input_tokens_estimate") or 0)
    output_tokens = int(safe_trace.get("output_token_estimate") or safe_trace.get("output_tokens_estimate") or 0)
    safe_trace["input_tokens_estimate"] = input_tokens
    safe_trace["output_tokens_estimate"] = output_tokens
    input_rate = float(os.getenv("MODEL_INPUT_COST_PER_1M", "0") or 0)
    output_rate = float(os.getenv("MODEL_OUTPUT_COST_PER_1M", "0") or 0)
    estimated_cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    payload = {
        "company_id": company_id,
        "lead_id": lead_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace": safe_trace,
        "estimated_cost": estimated_cost,
        "currency": "USD",
        "pricing_configured": bool(input_rate or output_rate),
    }
    row = SystemEvent(
        company_id=company_id,
        event_type="telemetry.ai_response",
        entity_id=entity_id,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def aggregate_pilot_metrics(db: Session, company_id: str | None) -> dict[str, Any]:
    query = db.query(SystemEvent).filter(
        (SystemEvent.event_type.like("pilot.%")) | (SystemEvent.event_type == "telemetry.ai_response")
    )
    if company_id is not None:
        query = query.filter(SystemEvent.company_id == company_id)
    rows = query.all()
    event_counts: dict[str, int] = {}
    model_calls = fallback_count = provider_errors = 0
    latency_values: list[float] = []
    input_tokens = output_tokens = 0
    estimated_cost = 0.0
    for row in rows:
        try:
            payload = json.loads(row.payload or "{}")
        except json.JSONDecodeError:
            continue
        if row.event_type.startswith("pilot."):
            event_name = row.event_type.removeprefix("pilot.")
            event_counts[event_name] = event_counts.get(event_name, 0) + 1
            continue
        trace = payload.get("trace") or {}
        model_calls += int(trace.get("model_call_count") or 0)
        input_tokens += int(trace.get("input_token_estimate") or trace.get("input_tokens_estimate") or 0)
        output_tokens += int(trace.get("output_token_estimate") or trace.get("output_tokens_estimate") or 0)
        if str(trace.get("response_path") or "").upper() == "FALLBACK":
            fallback_count += 1
        if trace.get("error_category") or trace.get("fallback_reason") not in {None, "provider_unavailable"}:
            provider_errors += 1
        if trace.get("latency_ms") is not None:
            latency_values.append(float(trace["latency_ms"]))
        estimated_cost += float(payload.get("estimated_cost") or 0)
    conversations = event_counts.get("first_public_conversation", 0)
    return {
        "company_id": company_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "activation": {
            "onboarding_completed": event_counts.get("merchant_onboarding_completed", 0),
            "catalog_first_valid_product": event_counts.get("catalog_first_valid_product", 0),
            "first_public_conversation": conversations,
        },
        "usage": event_counts,
        "reliability": {
            "ai_responses": len([row for row in rows if row.event_type == "telemetry.ai_response"]),
            "fallback_count": fallback_count,
            "provider_error_count": provider_errors,
            "average_response_latency_ms": (sum(latency_values) / len(latency_values)) if latency_values else None,
        },
        "economics": {
            "model_calls": model_calls,
            "input_tokens_estimate": input_tokens,
            "output_tokens_estimate": output_tokens,
            "estimated_model_cost_usd": round(estimated_cost, 8),
            "cost_per_conversation_usd": round(estimated_cost / conversations, 8) if conversations else None,
            "estimated": True,
        },
    }
