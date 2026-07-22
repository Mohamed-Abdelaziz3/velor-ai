"""Truthful, tenant-scoped operational impact reporting for Revenue Recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from statistics import median
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import CommercialEvent, FollowUpTask, Lead, Message, SystemEvent, get_phone_variants, normalize_whatsapp_number


PROGRESSION_TYPES = {
    "PRODUCT_SELECTED",
    "PURCHASE_INTENT_EXPRESSED",
    "PURCHASE_COMMITMENT",
    "PURCHASE_EXECUTION_REQUEST",
}


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payload(row: SystemEvent) -> dict[str, Any]:
    try:
        parsed = json.loads(row.payload or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _metric(value: Any, definition: str, *, status: str = "measured") -> dict[str, Any]:
    return {"value": value, "status": status, "definition": definition}


def _lead_identifiers(lead: Lead) -> set[str]:
    identifiers: set[str] = set()
    for value in (
        lead.external_customer_id,
        lead.whatsapp_jid,
        lead.customer_provided_phone,
        lead.phone,
        lead.whatsapp_number,
    ):
        if not value:
            continue
        identifiers.add(str(value))
        normalized = normalize_whatsapp_number(str(value))
        if normalized:
            identifiers.add(normalized)
            identifiers.update(get_phone_variants(normalized))
    return {value for value in identifiers if value}


def build_recovery_impact(
    db: Session,
    company_id: str,
    *,
    days: int = 30,
    channel: str = "all",
) -> dict[str, Any]:
    window_days = max(1, min(int(days or 30), 365))
    channel_filter = str(channel or "all").lower()
    if channel_filter not in {"all", "whatsapp", "web"}:
        raise ValueError("unsupported_channel")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)

    lead_query = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    )
    if channel_filter == "web":
        lead_query = lead_query.filter(Lead.channel_type == "VELOR_WEB_CHAT")
    elif channel_filter == "whatsapp":
        lead_query = lead_query.filter(Lead.channel_type != "VELOR_WEB_CHAT")
    leads = lead_query.all()
    lead_ids = {lead.id for lead in leads}

    telemetry_rows = db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type.like("pilot.%"),
        SystemEvent.created_at >= since,
    ).order_by(SystemEvent.created_at.asc(), SystemEvent.id.asc()).all()

    events: list[dict[str, Any]] = []
    for row in telemetry_rows:
        payload = _payload(row)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        lead_id = metadata.get("lead_id")
        if lead_id is not None:
            try:
                lead_id = int(lead_id)
            except (TypeError, ValueError):
                continue
            if lead_id not in lead_ids:
                continue
        events.append({
            "name": row.event_type.removeprefix("pilot."),
            "at": _utc(row.created_at) or since,
            "entity_id": row.entity_id,
            "metadata": metadata,
            "lead_id": lead_id,
        })

    def named(name: str) -> list[dict[str, Any]]:
        return [event for event in events if event["name"] == name]

    shown = named("opportunity_shown")
    opened = named("opportunity_opened")
    owner_actions = named("owner_action_started")
    unique_shown = {str(event["metadata"].get("queue_item_id")) for event in shown if event["metadata"].get("queue_item_id")}
    unique_opened = {str(event["metadata"].get("queue_item_id")) for event in opened if event["metadata"].get("queue_item_id")}

    handled_within_24 = 0
    for queue_id in unique_shown:
        shown_at = min(event["at"] for event in shown if str(event["metadata"].get("queue_item_id")) == queue_id)
        if any(
            str(event["metadata"].get("queue_item_id")) == queue_id
            and shown_at <= event["at"] <= shown_at + timedelta(hours=24)
            for event in owner_actions
        ):
            handled_within_24 += 1

    from services.owner_attention_projection_service import get_owner_attention_projection

    waiting_projection = get_owner_attention_projection(db, company_id, limit=100).get("items", [])
    waiting_count = len({
        int(item["lead_id"])
        for item in waiting_projection
        if item.get("projection_class") == "WAITING_ON_US" and int(item["lead_id"]) in lead_ids
    })

    identifiers_by_lead = {lead.id: _lead_identifiers(lead) for lead in leads}
    all_identifiers = {value for values in identifiers_by_lead.values() for value in values}
    response_seconds: list[float] = []
    if all_identifiers:
        inbound_rows = db.query(Message).filter(
            Message.company_id == company_id,
            Message.user_id.in_(all_identifiers),
            Message.direction == "incoming",
            Message.sender.in_(("user", "customer")),
            Message.created_at >= since,
            Message.is_deleted == False,
        ).all()
        inbound_by_id = {row.id: row for row in inbound_rows}
        if inbound_by_id:
            replies = db.query(Message).filter(
                Message.company_id == company_id,
                Message.in_reply_to_message_id.in_(list(inbound_by_id)),
                Message.direction == "outgoing",
                Message.sender == "owner",
                Message.is_deleted == False,
            ).all()
            for reply in replies:
                source = inbound_by_id.get(reply.in_reply_to_message_id)
                source_at = _utc(source.created_at) if source else None
                reply_at = _utc(reply.created_at)
                if source_at and reply_at and reply_at >= source_at:
                    response_seconds.append((reply_at - source_at).total_seconds())

    from services.follow_up_service import reactivate_due_snoozed

    if reactivate_due_snoozed(db, company_id, now=now):
        db.commit()
    followups = db.query(FollowUpTask).filter(
        FollowUpTask.company_id == company_id,
        FollowUpTask.lead_id.in_(lead_ids) if lead_ids else FollowUpTask.id == -1,
    ).all()
    created_followups = [task for task in followups if (_utc(task.created_at) or since) >= since]
    completed_followups = [task for task in followups if task.completed_at and _utc(task.completed_at) >= since]
    completed_on_time = [
        task for task in completed_followups
        if _utc(task.due_at) and _utc(task.completed_at) and _utc(task.completed_at) <= _utc(task.due_at)
    ]
    overdue = [task for task in followups if task.status == "pending" and _utc(task.due_at) and _utc(task.due_at) < now]

    suggestion_generated = named("suggestion_generated")
    suggestion_inserted = named("suggestion_inserted")
    suggestion_sent = named("suggestion_sent")
    suggestion_dismissed = named("suggestion_dismissed")
    suggestion_stale = named("suggestion_stale_blocked")
    sent_edited = [event for event in suggestion_sent if event["metadata"].get("edited") is True]
    sent_unedited = [event for event in suggestion_sent if event["metadata"].get("edited") is False]

    progression_rows = db.query(CommercialEvent).filter(
        CommercialEvent.company_id == company_id,
        CommercialEvent.lead_id.in_(lead_ids) if lead_ids else CommercialEvent.id == -1,
        CommercialEvent.event_type.in_(sorted(PROGRESSION_TYPES)),
        CommercialEvent.observed_at >= since,
    ).all()
    progressed_leads = {
        action["lead_id"]
        for action in owner_actions
        if action["lead_id"] is not None and any(
            row.lead_id == action["lead_id"]
            and (_utc(row.observed_at) or since) > action["at"]
            for row in progression_rows
        )
    }

    gap_rows = db.query(CommercialEvent).filter(
        CommercialEvent.company_id == company_id,
        CommercialEvent.lead_id.in_(lead_ids) if lead_ids else CommercialEvent.id == -1,
        CommercialEvent.event_type == "KNOWLEDGE_GAP_HIT",
        CommercialEvent.observed_at >= since,
    ).all()
    resolved_gap_leads = {event["lead_id"] for event in named("knowledge_gap_resolved") if event["lead_id"] is not None}
    gap_counts: dict[int, int] = {}
    for row in gap_rows:
        gap_counts[row.lead_id] = gap_counts.get(row.lead_id, 0) + 1
    unresolved_repeated_gaps = len({lead_id for lead_id, count in gap_counts.items() if count >= 2 and lead_id not in resolved_gap_leads})

    metrics = {
        "unique_active_opportunities_shown": _metric(len(unique_shown), "Unique source-linked queue items rendered in the selected window."),
        "unique_opportunities_opened": _metric(len(unique_opened), "Unique source-linked queue items opened by the owner."),
        "owner_actions_started": _metric(len(owner_actions), "Owner arrivals in the canonical workspace from a source-linked queue item."),
        "priority_signals_handled_within_24_hours": _metric(handled_within_24, "Shown queue items followed by an owner workspace action within 24 hours."),
        "current_customers_waiting_for_response": _metric(waiting_count, "Current unanswered customer turns with a deterministic operational reason."),
        "median_owner_response_time_seconds": _metric(median(response_seconds) if response_seconds else None, "Median elapsed time from a source customer turn to its canonically linked owner reply.", status="measured" if response_seconds else "unavailable"),
        "follow_ups_created": _metric(len(created_followups), "Durable follow-up tasks created in the selected window."),
        "follow_ups_completed": _metric(len(completed_followups), "Durable follow-up tasks completed in the selected window."),
        "follow_ups_completed_on_time": _metric(len(completed_on_time), "Completed follow-ups whose server completion timestamp is at or before due time."),
        "overdue_follow_ups": _metric(len(overdue), "Current pending follow-ups whose due time has passed."),
        "suggestion_generations": _metric(len(suggestion_generated), "Durably created source-linked suggested replies."),
        "suggestion_insertions": _metric(len(suggestion_inserted), "Validated owner insert interactions; insertion does not mean use."),
        "suggestion_sends": _metric(len(suggestion_sent), "Verified suggestion-derived messages persisted after a successful send."),
        "suggestion_sends_without_edits": _metric(len(sent_unedited), "Verified suggestion sends whose submitted text exactly matched the stored variant."),
        "suggestion_sends_with_edits": _metric(len(sent_edited), "Verified suggestion sends whose submitted text differed from the stored variant."),
        "suggestion_dismissals": _metric(len(suggestion_dismissed), "Suggested replies dismissed after a successful server state transition."),
        "stale_suggestion_blocks": _metric(len(suggestion_stale), "Suggestion-derived sends rejected because the conversation advanced."),
        "conversations_with_subsequent_commercial_progress": _metric(len(progressed_leads), "Conversations with an explicit later progression event after an owner action; this is temporal association, not causation."),
        "unresolved_repeated_knowledge_gaps": _metric(unresolved_repeated_gaps, "Conversations with at least two persisted knowledge-gap events and no later recorded resolution."),
    }

    unavailable_definition = "Trusted order and payment providers are not connected; unknown outcomes remain null, never zero."
    financial_outcomes = {
        key: _metric(None, unavailable_definition, status="not_connected")
        for key in (
            "confirmed_orders",
            "paid_outcomes",
            "paid_amount",
            "recovered_revenue",
            "attributed_revenue",
        )
    }
    return {
        "status": "measured_operational_only",
        "tenant_scope": company_id,
        "filters_applied": {"days": window_days, "channel": channel_filter},
        "data_window": {"from": since.isoformat(), "to": now.isoformat()},
        "generated_at": now.isoformat(),
        "metrics": metrics,
        "financial_outcomes": financial_outcomes,
        "outcome_status": "not_connected",
        "outcome_explanation_ar": "مصادر الطلبات والمدفوعات الموثوقة غير متصلة؛ لذلك تظل النتائج المالية غير متاحة وليست صفراً.",
        "causality_note": "Subsequent progress is a temporal observation after owner action and is not attributed causally to VELOR.",
    }
