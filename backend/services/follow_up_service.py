"""Tenant-scoped lifecycle for the existing durable ``FollowUpTask`` model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Iterable, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import CommercialEvent, FollowUpTask, Lead, Message, get_phone_variants, normalize_whatsapp_number


ACTIVE_STATUSES = {"pending", "snoozed"}
TERMINAL_STATUSES = {"completed", "dismissed", "cancelled", "superseded"}
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
TERMINAL_LEAD_VALUES = {"won", "lost", "closed won", "closed lost", "sale"}

TRANSITIONS = {
    "pending": {"completed", "dismissed", "snoozed", "cancelled", "superseded"},
    "snoozed": {"pending", "completed", "dismissed", "cancelled", "superseded"},
}


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    normalized = _utc(value)
    return normalized.isoformat().replace("+00:00", "Z") if normalized else None


def is_terminal_lead(lead: Lead) -> bool:
    return any(
        str(value or "").strip().casefold() in TERMINAL_LEAD_VALUES
        for value in (lead.stage, lead.status)
    )


def serialize_follow_up(task: FollowUpTask) -> dict[str, Any]:
    lead = task.lead
    return {
        "task_id": task.id,
        "lead_id": task.lead_id,
        "display_label": (lead.name if lead else None) or f"Customer {task.lead_id}",
        "category": task.category,
        "reason_code": task.reason_code,
        "reason": task.explanation,
        "source_type": task.source_type,
        "source_identifier": task.source_identifier,
        "source_event_id": task.source_event_id,
        "source_message_internal_id": task.source_message_internal_id,
        "priority": task.priority,
        "due_at": _iso(task.due_at),
        "status": task.status,
        "completed_at": _iso(task.completed_at),
        "dismissed_at": _iso(task.dismissed_at),
        "snoozed_until": _iso(task.snoozed_until),
        "completion_reference": task.completion_reference,
        "suggested_message": task.suggested_message,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "channel": getattr(lead, "channel_type", None),
        "workspace_path": f"/inbox/{task.lead_id}",
    }


def _idempotency_key(*, lead_id: int, source_type: str, source_identifier: str, reason_code: str) -> str:
    raw = f"{lead_id}|{source_type}|{source_identifier}|{reason_code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _record_transition(
    db: Session,
    task: FollowUpTask,
    event_name: str,
    *,
    actor_type: Optional[str] = None,
    transition_key: Optional[str] = None,
) -> None:
    from services.pilot_telemetry_service import record_pilot_event

    record_pilot_event(
        db,
        event_name=event_name,
        company_id=task.company_id,
        actor_type=actor_type or (
            "system"
            if event_name in {"follow_up_created", "follow_up_cancelled", "follow_up_superseded"}
            else "owner"
        ),
        entity_id=task.id,
        source="follow_up_lifecycle",
        idempotency_key=(
            f"follow-up:{task.id}:{event_name}:{transition_key}"
            if transition_key
            else f"follow-up:{task.id}:{event_name}"
        ),
        metadata={
            "lead_id": task.lead_id,
            "task_id": task.id,
            "reason_code": task.reason_code,
            "status": task.status,
            "due_at": _iso(task.due_at),
            "source_message_internal_id": task.source_message_internal_id,
        },
        commit=False,
    )


def create_follow_up(
    db: Session,
    *,
    company_id: str,
    lead_id: int,
    source_type: str,
    source_identifier: str,
    reason_code: str,
    due_at: datetime,
    category: str = "FOLLOW_UP_DUE",
    priority: int = 50,
    source_event_id: Optional[int] = None,
    source_message_internal_id: Optional[str] = None,
    explanation: Optional[str] = None,
    suggested_message: Optional[str] = None,
    commit: bool = True,
) -> Optional[FollowUpTask]:
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead or is_terminal_lead(lead):
        return None

    key = _idempotency_key(
        lead_id=lead_id,
        source_type=source_type,
        source_identifier=source_identifier,
        reason_code=reason_code,
    )
    existing = db.query(FollowUpTask).filter(
        FollowUpTask.company_id == company_id,
        FollowUpTask.idempotency_key == key,
    ).first()
    if existing:
        return existing

    task = FollowUpTask(
        company_id=company_id,
        lead_id=lead_id,
        task_level=max(1, min(4, (int(priority) + 24) // 25)),
        task_type=str(reason_code)[:100],
        source_type=str(source_type)[:50],
        source_identifier=str(source_identifier)[:160],
        source_event_id=source_event_id,
        source_message_internal_id=source_message_internal_id,
        reason_code=str(reason_code)[:100],
        idempotency_key=key,
        category=str(category)[:50],
        priority=max(1, min(100, int(priority))),
        status="pending",
        due_at=_utc(due_at) or datetime.now(timezone.utc),
        explanation=(str(explanation)[:1000] if explanation else None),
        suggested_message=(str(suggested_message)[:1000] if suggested_message else None),
    )
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
    except IntegrityError:
        task = db.query(FollowUpTask).filter(
            FollowUpTask.company_id == company_id,
            FollowUpTask.idempotency_key == key,
        ).one()
        return task

    _record_transition(db, task, "follow_up_created")
    if commit:
        db.commit()
        db.refresh(task)
    return task


def reactivate_due_snoozed(db: Session, company_id: str, *, now: Optional[datetime] = None) -> int:
    current = _utc(now) or datetime.now(timezone.utc)
    tasks = db.query(FollowUpTask).join(Lead, Lead.id == FollowUpTask.lead_id).filter(
        FollowUpTask.company_id == company_id,
        FollowUpTask.status == "snoozed",
        FollowUpTask.snoozed_until <= current,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).all()
    for task in tasks:
        previous_snoozed_until = _iso(task.snoozed_until)
        task.status = "pending"
        task.due_at = max(_utc(task.due_at) or current, current)
        task.snoozed_until = None
        _record_transition(
            db,
            task,
            "follow_up_reactivated",
            actor_type="system",
            transition_key=previous_snoozed_until,
        )
    return len(tasks)


def list_follow_ups(
    db: Session,
    company_id: str,
    *,
    statuses: Optional[Iterable[str]] = None,
    lead_id: Optional[int] = None,
    due_only: bool = False,
    limit: int = 100,
    commit_reactivation: bool = True,
) -> list[FollowUpTask]:
    reactivated = reactivate_due_snoozed(db, company_id)
    if reactivated and commit_reactivation:
        db.commit()
    requested = {str(value).lower() for value in (statuses or ACTIVE_STATUSES)}
    if not requested <= ALL_STATUSES:
        raise ValueError("unsupported_follow_up_status")
    query = db.query(FollowUpTask).join(Lead, Lead.id == FollowUpTask.lead_id).filter(
        FollowUpTask.company_id == company_id,
        FollowUpTask.status.in_(sorted(requested)),
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    )
    if lead_id is not None:
        query = query.filter(FollowUpTask.lead_id == lead_id)
    if due_only:
        query = query.filter(
            FollowUpTask.status == "pending",
            FollowUpTask.due_at <= datetime.now(timezone.utc),
        )
    return query.order_by(FollowUpTask.due_at.asc(), FollowUpTask.priority.desc(), FollowUpTask.id.asc()).limit(
        max(1, min(int(limit or 100), 200))
    ).all()


def transition_follow_up(
    db: Session,
    *,
    company_id: str,
    task_id: int,
    target_status: str,
    snoozed_until: Optional[datetime] = None,
    completion_reference: Optional[str] = None,
    actor_type: str = "owner",
    commit: bool = True,
) -> Optional[FollowUpTask]:
    task = db.query(FollowUpTask).join(Lead, Lead.id == FollowUpTask.lead_id).filter(
        FollowUpTask.id == task_id,
        FollowUpTask.company_id == company_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).with_for_update().first()
    if not task:
        return None

    target = str(target_status).lower()
    if target == task.status:
        return task
    if target not in TRANSITIONS.get(task.status, set()):
        raise ValueError("invalid_follow_up_transition")

    now = datetime.now(timezone.utc)
    if target == "snoozed":
        until = _utc(snoozed_until)
        if until is None or until <= now or until > now + timedelta(days=365):
            raise ValueError("invalid_snooze_time")
        task.snoozed_until = until
    else:
        task.snoozed_until = None
    task.status = target
    if target == "completed":
        task.completed_at = now
        task.completion_reference = str(completion_reference)[:160] if completion_reference else None
    elif target == "dismissed":
        task.dismissed_at = now

    event_name = f"follow_up_{target}"
    _record_transition(
        db,
        task,
        event_name,
        actor_type=actor_type,
        transition_key=_iso(task.snoozed_until) if target == "snoozed" else None,
    )
    if target == "completed" and task.reason_code == "KNOWLEDGE_GAP_HIT":
        from services.pilot_telemetry_service import record_pilot_event

        record_pilot_event(
            db,
            event_name="knowledge_gap_resolved",
            company_id=task.company_id,
            actor_type=actor_type,
            entity_id=task.id,
            source="follow_up_completion",
            idempotency_key=f"follow-up:{task.id}:knowledge-gap-resolved",
            metadata={
                "lead_id": task.lead_id,
                "task_id": task.id,
                "reason_code": task.reason_code,
                "source_message_internal_id": task.source_message_internal_id,
            },
            commit=False,
        )
    if commit:
        db.commit()
        db.refresh(task)
    return task


def supersede_for_new_customer_turn(db: Session, message: Message, *, commit: bool = False) -> int:
    if message.direction != "incoming" or message.sender not in {"user", "customer"}:
        return 0
    base = normalize_whatsapp_number(message.user_id)
    identifiers = set(get_phone_variants(base)) | {message.user_id, base}
    lead = db.query(Lead).filter(
        Lead.company_id == message.company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
        or_(
            Lead.external_customer_id == message.user_id,
            Lead.whatsapp_jid == message.user_id,
            Lead.phone.in_(identifiers),
            Lead.whatsapp_number.in_(identifiers),
        ),
    ).first()
    if not lead:
        return 0
    tasks = db.query(FollowUpTask).filter(
        FollowUpTask.company_id == message.company_id,
        FollowUpTask.lead_id == lead.id,
        FollowUpTask.status.in_(sorted(ACTIVE_STATUSES)),
        FollowUpTask.source_message_internal_id.is_not(None),
        FollowUpTask.source_message_internal_id != message.internal_message_id,
    ).all()
    for task in tasks:
        transition_follow_up(
            db,
            company_id=message.company_id,
            task_id=task.id,
            target_status="superseded",
            completion_reference=message.internal_message_id,
            actor_type="system",
            commit=False,
        )
    if tasks and commit:
        db.commit()
    return len(tasks)


def complete_reply_required_tasks(
    db: Session,
    *,
    company_id: str,
    lead: Lead,
    outbound_message: Message,
    source_message_internal_id: Optional[str] = None,
    commit: bool = False,
) -> int:
    source_id = source_message_internal_id
    if not source_id:
        identifiers = set()
        for value in (lead.external_customer_id, lead.whatsapp_jid, lead.phone, lead.whatsapp_number):
            if value:
                identifiers.add(str(value))
                normalized = normalize_whatsapp_number(str(value))
                identifiers.add(normalized)
                identifiers.update(get_phone_variants(normalized))
        latest = db.query(Message).filter(
            Message.company_id == company_id,
            Message.user_id.in_([item for item in identifiers if item]),
            Message.direction == "incoming",
            Message.sender.in_(("user", "customer")),
            Message.is_deleted == False,
        ).order_by(Message.created_at.desc(), Message.id.desc()).first()
        source_id = latest.internal_message_id if latest else None
    if not source_id:
        return 0

    tasks = db.query(FollowUpTask).filter(
        FollowUpTask.company_id == company_id,
        FollowUpTask.lead_id == lead.id,
        FollowUpTask.status.in_(sorted(ACTIVE_STATUSES)),
        FollowUpTask.source_message_internal_id == source_id,
    ).all()
    for task in tasks:
        transition_follow_up(
            db,
            company_id=company_id,
            task_id=task.id,
            target_status="completed",
            completion_reference=outbound_message.internal_message_id,
            actor_type="system",
            commit=False,
        )
    if tasks and commit:
        db.commit()
    return len(tasks)


def cancel_for_terminal_lead(db: Session, *, company_id: str, lead_id: int, commit: bool = False) -> int:
    tasks = db.query(FollowUpTask).filter(
        FollowUpTask.company_id == company_id,
        FollowUpTask.lead_id == lead_id,
        FollowUpTask.status.in_(sorted(ACTIVE_STATUSES)),
    ).all()
    for task in tasks:
        transition_follow_up(
            db,
            company_id=company_id,
            task_id=task.id,
            target_status="cancelled",
            actor_type="system",
            commit=False,
        )
    if tasks and commit:
        db.commit()
    return len(tasks)


def sync_follow_ups_from_attention(db: Session, company_id: str, *, now: Optional[datetime] = None) -> int:
    """Create idempotent tasks from the existing canonical owner projection."""
    from services.owner_attention_projection_service import get_owner_attention_projection

    current = _utc(now) or datetime.now(timezone.utc)
    projection = get_owner_attention_projection(db, company_id, limit=100)
    due_policy = {
        "PROCESSING_FAILURE": (0, 100),
        "PROCESSING_STUCK": (0, 98),
        "HUMAN_TAKEOVER_ACTIVE": (0, 96),
        "PURCHASE_EXECUTION_REQUEST": (1, 94),
        "PURCHASE_COMMITMENT": (4, 90),
        "PURCHASE_INTENT_EXPRESSED": (8, 86),
        "START_INTENT": (8, 84),
        "PRICE_OBJECTION_PRESENT": (24, 78),
        "CONVERSATION_STALLED": (24, 72),
        "REGRESSING_MOMENTUM": (24, 70),
        "HESITATION_SIGNAL": (24, 68),
        "KNOWLEDGE_GAP_HIT": (24, 76),
    }
    candidates = []
    for item in projection.get("items") or []:
        reason_code = str(item.get("reason_code") or "")
        policy = due_policy.get(reason_code)
        if not policy:
            continue
        evidence = item.get("evidence") or []
        source_message_id = next(
            (row.get("source_message_internal_id") for row in evidence if row.get("source_message_internal_id")),
            None,
        )
        source_identifier = source_message_id or str(item.get("id"))
        key = _idempotency_key(
            lead_id=int(item["lead_id"]),
            source_type="owner_attention_projection",
            source_identifier=source_identifier,
            reason_code=reason_code,
        )
        candidates.append((item, policy, source_message_id, source_identifier, key, "owner_attention_projection", None, reason_code))

    knowledge_gaps = db.query(CommercialEvent).join(Lead, Lead.id == CommercialEvent.lead_id).filter(
        CommercialEvent.company_id == company_id,
        CommercialEvent.event_type == "KNOWLEDGE_GAP_HIT",
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
        Lead.stage.notin_(["Won", "Lost"]),
    ).order_by(CommercialEvent.observed_at.desc(), CommercialEvent.id.desc()).limit(100).all()
    for event in knowledge_gaps:
        source_identifier = event.event_hash or event.source_message_internal_id
        key = _idempotency_key(
            lead_id=event.lead_id,
            source_type="commercial_event",
            source_identifier=source_identifier,
            reason_code="KNOWLEDGE_GAP_HIT",
        )
        candidates.append((
            {"lead_id": event.lead_id, "why": "A persisted knowledge gap still needs an owner-confirmed resolution."},
            due_policy["KNOWLEDGE_GAP_HIT"],
            event.source_message_internal_id,
            source_identifier,
            key,
            "commercial_event",
            event.id,
            "KNOWLEDGE_GAP_HIT",
        ))

    existing_keys = {
        row[0]
        for row in db.query(FollowUpTask.idempotency_key).filter(
            FollowUpTask.company_id == company_id,
            FollowUpTask.idempotency_key.in_([row[4] for row in candidates]),
        ).all()
    } if candidates else set()
    created = 0
    for item, policy, source_message_id, source_identifier, key, source_type, source_event_id, reason_code in candidates:
        if key in existing_keys:
            continue
        task = create_follow_up(
            db,
            company_id=company_id,
            lead_id=int(item["lead_id"]),
            source_type=source_type,
            source_identifier=source_identifier,
            source_event_id=source_event_id,
            source_message_internal_id=source_message_id,
            reason_code=reason_code,
            category="FOLLOW_UP_DUE",
            priority=policy[1],
            due_at=current + timedelta(hours=policy[0]),
            explanation=item.get("why"),
            commit=False,
        )
        if task is not None and key not in existing_keys:
            created += 1
    if created:
        db.commit()
    return created
