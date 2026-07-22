"""Atomic persistence boundary for one V2 public Web Chat turn."""

import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from database import (
    Company,
    Lead,
    LeadMemory,
    LeadEvent,
    Message,
    MessageEvent,
    SessionLocal,
    SystemEvent,
    _upsert_usage_in_session,
)
from services.commercial_intelligence_service import persist_commercial_turn_in_session
from services.workspace_suggestion_service import invalidate_prior_suggestions_for_inbound_message


def _apply_bounded_lead_update(lead: Lead, payload: Optional[Dict[str, Any]]) -> None:
    """Apply only fields already produced by the deterministic V2 pipeline."""
    if not payload:
        return
    text_fields = {
        "interest",
        "ai_summary",
        "last_message_preview",
        "conversation_state",
        "customer_provided_phone",
        "name",
        "temperature",
        "status",
        "pending_question",
        "sales_state_snapshot",
    }
    bool_fields = {"is_hot_deal", "needs_human_intervention"}
    for field in text_fields:
        value = payload.get(field)
        if value is not None and hasattr(lead, field):
            setattr(lead, field, value)
    for field in bool_fields:
        if field in payload and hasattr(lead, field):
            setattr(lead, field, bool(payload[field]))
    # Conversation generation may have started before an owner took control.
    # A stale response is therefore allowed to engage a handoff, but it must
    # never clear a pause that may have been committed by a newer owner action.
    if payload.get("is_paused") is True:
        lead.is_paused = True
    if payload.get("lead_score") is not None:
        lead.lead_score = int(payload["lead_score"])
    if payload.get("budget") is not None:
        if lead.memory is None:
            lead.memory = LeadMemory()
        lead.memory.budget = json.dumps(
            {
                "value": float(payload["budget"]),
                "currency": str(payload.get("budget_currency") or "EGP")[:8],
                "source": "explicit_customer_message",
            },
            ensure_ascii=False,
        )
    preference_snapshot = payload.get("preference_memory_snapshot")
    communication_snapshot = payload.get("communication_profile_snapshot")
    if isinstance(preference_snapshot, dict) or isinstance(communication_snapshot, dict):
        if lead.memory is None:
            lead.memory = LeadMemory()
        existing_preferences: Dict[str, Any] = {}
        if lead.memory.preferences:
            try:
                parsed_preferences = json.loads(lead.memory.preferences)
                if isinstance(parsed_preferences, dict):
                    existing_preferences = parsed_preferences
            except (TypeError, ValueError, json.JSONDecodeError):
                existing_preferences = {}
        if isinstance(preference_snapshot, dict):
            existing_communication = existing_preferences.get("communication_profile")
            existing_preferences = dict(preference_snapshot)
            if existing_communication is not None:
                existing_preferences["communication_profile"] = existing_communication
        if isinstance(communication_snapshot, dict):
            existing_preferences["communication_profile"] = communication_snapshot
        lead.memory.preferences = json.dumps(existing_preferences, ensure_ascii=False)
        lead.memory.last_updated = datetime.now(timezone.utc)
    lead.updated_at = datetime.now(timezone.utc)


def _project_inbound_once(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    customer_text: str,
    inbound: Message,
    lead: Lead,
) -> None:
    """Persist the observable inbound half of a turn exactly once."""
    inbound_projected = db.query(MessageEvent.id).filter(
        MessageEvent.message_id == inbound.id,
        MessageEvent.status == "received",
    ).first()
    if inbound_projected is not None:
        return

    inbound_timestamp = datetime.now(timezone.utc).isoformat()
    inbound_payload = json.dumps(
        {
            "message_id": inbound.internal_message_id,
            "wa_message_id": inbound.wa_message_id,
            "sender": "user",
            "direction": "incoming",
            "text": customer_text,
            "user_id": user_id,
            "delivery_status": "received",
            "timestamp": inbound_timestamp,
        },
        ensure_ascii=False,
    )
    db.add(MessageEvent(message_id=inbound.id, status="received"))
    db.add_all(
        [
            SystemEvent(
                company_id=company_id,
                event_type="message.created",
                entity_id=inbound.internal_message_id,
                payload=inbound_payload,
            ),
            SystemEvent(
                company_id=company_id,
                event_type="message.received",
                entity_id=inbound.internal_message_id,
                payload=inbound_payload,
            ),
        ]
    )
    lead.last_message = customer_text
    lead.last_message_sender = "user"
    lead.conversation_count = (lead.conversation_count or 0) + 1
    lead.last_contact_date = datetime.now(timezone.utc)

    from services.evidence_engine import persist_evidence_for_message

    persist_evidence_for_message(db, inbound)
    _upsert_usage_in_session(db, company_id, messages=1, requests=1)


def current_auto_reply_block_reason(
    db: Session,
    *,
    company_id: str,
    lead_id: int,
    inbound_internal_id: str,
    allow_ai_handoff_pause: bool = False,
) -> Optional[str]:
    """Return a current server-side reason that forbids an automatic reply.

    Queries deliberately refresh the control rows instead of trusting objects
    captured before an LLM/network await.  A linked assistant draft for this
    exact inbound is excluded so callers can safely re-check immediately after
    persistence and before external dispatch.
    """
    inbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.internal_message_id == inbound_internal_id,
        Message.direction == "incoming",
    ).first()
    if inbound is None:
        return "source_unavailable"

    newer_turn = (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.user_id == inbound.user_id,
            Message.id > inbound.id,
            ~(
                (Message.sender == "assistant")
                & (Message.direction == "outgoing")
                & (Message.in_reply_to_message_id == inbound.id)
            ),
        )
        .order_by(Message.id.desc())
        .first()
    )
    if newer_turn is not None:
        if newer_turn.direction == "outgoing":
            return "owner_replied"
        return "conversation_advanced"

    paused = db.query(Lead.is_paused).filter(
        Lead.company_id == company_id,
        Lead.id == lead_id,
        Lead.is_deleted == False,
    ).scalar()
    if paused and not allow_ai_handoff_pause:
        return "human_takeover_active"

    enabled = db.query(Company.bot_auto_reply_enabled).filter(
        Company.company_id == company_id,
        Company.is_deleted == False,
    ).scalar()
    if enabled is False:
        return "company_auto_reply_disabled"
    return None


def cancel_persisted_auto_reply(
    db: Session,
    *,
    company_id: str,
    inbound_internal_id: str,
    outbound_internal_id: str,
    reason: str,
) -> None:
    """Fence an already-persisted pending reply before channel dispatch."""
    inbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.internal_message_id == inbound_internal_id,
    ).first()
    outbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.internal_message_id == outbound_internal_id,
        Message.direction == "outgoing",
        Message.sender == "assistant",
    ).first()
    if outbound is not None and outbound.delivery_status not in {"sent", "delivered", "read"}:
        outbound.delivery_status = "canceled"
        db.add(MessageEvent(message_id=outbound.id, status="canceled"))
    if inbound is not None:
        inbound.processing_status = "intentionally_skipped"
        inbound.processing_completed_at = datetime.now(timezone.utc)
    db.add(
        SystemEvent(
            company_id=company_id,
            event_type="auto_reply.skipped",
            entity_id=inbound_internal_id,
            payload=json.dumps(
                {
                    "reason": str(reason or "control_changed")[:80],
                    "auto_reply_skipped": True,
                    "outbound_internal_id": outbound_internal_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()


def persist_v2_public_turn_atomic(
    *,
    db: Optional[Session] = None,
    company_id: str,
    lead_id: int,
    user_id: str,
    customer_text: str,
    assistant_text: str,
    inbound_internal_id: str,
    processing_claim_attempt: int,
    lead_update: Optional[Dict[str, Any]],
    decision: Any,
    sales_snapshot: Any,
    objection_snapshot: Any = None,
    recommendation_decision: Any = None,
    response_envelope: Optional[Dict[str, Any]] = None,
    conversation_action: Optional[Dict[str, Any]] = None,
    trace: Optional[Dict[str, Any]] = None,
    channel_type: str = "VELOR_WEB_CHAT",
    outbound_delivery_status: str = "sent",
    telemetry_source: Optional[str] = None,
    failure_stage: Optional[str] = None,
    enforce_auto_reply_guard: bool = False,
) -> Optional[Dict[str, Any]]:
    """Commit a complete V2 customer turn once, or commit none of it.

    Despite the compatibility name, this is the canonical channel-agnostic V2
    executor. Claim ownership is checked and completed inside the same
    transaction as the assistant row and commercial projection. A timed-out or
    superseded worker therefore cannot leave a reply without its lineage, nor
    can a retry call the provider after a committed turn.
    """
    channel_type = str(channel_type or "VELOR_WEB_CHAT")
    outbound_delivery_status = str(outbound_delivery_status or "pending")
    telemetry_source = telemetry_source or (
        "public_chat"
        if channel_type == "VELOR_WEB_CHAT"
        else (
            "meta_whatsapp"
            if channel_type == "WHATSAPP_META"
            else "whatsapp_gateway"
        )
    )
    def fail_after(stage: str) -> None:
        # A private fault seam used only by transactional regression tests.
        # It exercises the same rollback path as a real persistence failure.
        if failure_stage == stage:
            raise RuntimeError(f"public_turn_fault:{stage}")

    # Public HTTP V2 passes its open session so the inbound lease, response,
    # action, lineage, invalidation, telemetry, and claim completion share one
    # transaction. Direct callers retain an isolated session for testability.
    with (nullcontext(db) if db is not None else SessionLocal()) as db:
        try:
            inbound = (
                db.query(Message)
                .filter(
                    Message.company_id == company_id,
                    Message.internal_message_id == inbound_internal_id,
                    Message.direction == "incoming",
                    Message.sender.in_(("user", "customer")),
                    Message.processing_status == "processing",
                    Message.processing_attempts == processing_claim_attempt,
                )
                .first()
            )
            if inbound is None or inbound.message != customer_text:
                db.rollback()
                return None

            lead = (
                db.query(Lead)
                .execution_options(populate_existing=True)
                .filter(
                    Lead.company_id == company_id,
                    Lead.id == lead_id,
                    Lead.is_deleted == False,
                )
                .with_for_update()
                .first()
            )
            if lead is None:
                raise RuntimeError("public_chat_lead_missing")

            if enforce_auto_reply_guard:
                company_control = (
                    db.query(Company)
                    .execution_options(populate_existing=True)
                    .filter(
                        Company.company_id == company_id,
                        Company.is_deleted == False,
                    )
                    .with_for_update()
                    .first()
                )
                if company_control is None:
                    raise RuntimeError("public_chat_company_missing")
                block_reason = current_auto_reply_block_reason(
                    db,
                    company_id=company_id,
                    lead_id=lead.id,
                    inbound_internal_id=inbound.internal_message_id,
                )
                if block_reason:
                    _project_inbound_once(
                        db,
                        company_id=company_id,
                        user_id=user_id,
                        customer_text=customer_text,
                        inbound=inbound,
                        lead=lead,
                    )
                    inbound.processing_status = "intentionally_skipped"
                    inbound.processing_completed_at = datetime.now(timezone.utc)
                    db.add(
                        SystemEvent(
                            company_id=company_id,
                            event_type="auto_reply.skipped",
                            entity_id=inbound.internal_message_id,
                            payload=json.dumps(
                                {
                                    "reason": block_reason,
                                    "auto_reply_skipped": True,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    db.commit()

                    if block_reason in {"human_takeover_active", "company_auto_reply_disabled"}:
                        try:
                            from services.workspace_suggestion_service import create_workspace_suggestion_for_message

                            create_workspace_suggestion_for_message(
                                db,
                                company_id,
                                user_id,
                                inbound.internal_message_id,
                                block_reason,
                            )
                        except Exception:
                            db.rollback()
                    return {
                        "auto_reply_skipped": True,
                        "reason": block_reason,
                        "internal_id": inbound.internal_message_id,
                        "lead_id": lead.id,
                    }

            # Fence the exact accepted attempt before any dependent state is
            # staged.  A second executor that raced this worker cannot emit a
            # duplicate reply or execute the offered action a second time.
            claim_fenced = (
                db.query(Message)
                .filter(
                    Message.id == inbound.id,
                    Message.processing_status == "processing",
                    Message.processing_attempts == processing_claim_attempt,
                )
                .update({Message.processing_status: "finalizing"}, synchronize_session=False)
            )
            if claim_fenced != 1:
                db.rollback()
                return None

            # A V2 inbound claim is intentionally a bare idempotency lease.
            # Stage its observable projection only with the accepted result so
            # a failed answer cannot leave evidence, usage, SSE rows, or lead
            # activity behind.
            _project_inbound_once(
                db,
                company_id=company_id,
                user_id=user_id,
                customer_text=customer_text,
                inbound=inbound,
                lead=lead,
            )
            fail_after("inbound_projection")
            _apply_bounded_lead_update(lead, lead_update)
            fail_after("lead_update")

            internal_id = str(uuid.uuid4())
            public_message_id = f"pub-{uuid.uuid4().hex}"
            outbound = Message(
                internal_message_id=internal_id,
                public_message_id=public_message_id,
                company_id=company_id,
                user_id=user_id,
                sender="assistant",
                direction="outgoing",
                message=assistant_text,
                delivery_status=outbound_delivery_status,
                processing_status="completed",
                in_reply_to_message_id=inbound.id,
            )
            db.add(outbound)
            db.flush()
            fail_after("outbound")
            db.add(
                MessageEvent(
                    message_id=outbound.id,
                    status=outbound_delivery_status,
                )
            )
            fail_after("message_event")
            event_payload = json.dumps(
                {
                    "message_id": internal_id,
                    "sender": "assistant",
                    "direction": "outgoing",
                    "text": assistant_text,
                    "user_id": user_id,
                    "delivery_status": outbound_delivery_status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    # A public-safe, additive rendering contract is persisted
                    # with the message event so reloads and idempotent replays
                    # cannot lose cards, actions, or handoff status.
                    "response": response_envelope,
                    "in_reply_to": inbound_internal_id,
                },
                ensure_ascii=False,
            )
            db.add_all(
                [
                    SystemEvent(
                        company_id=company_id,
                        event_type="message.created",
                        entity_id=internal_id,
                        payload=event_payload,
                    ),
                    SystemEvent(
                        company_id=company_id,
                        event_type=(
                            "message.sent"
                            if outbound_delivery_status in {"sent", "delivered", "read"}
                            else "message.queued"
                        ),
                        entity_id=internal_id,
                        payload=event_payload,
                    ),
                ]
            )
            fail_after("response_event")

            if conversation_action and conversation_action.get("status") == "executed":
                action_type = str(conversation_action.get("type") or "")
                if action_type:
                    db.add(LeadEvent(
                        lead_id=lead.id,
                        event_type=f"conversation_action:{action_type}",
                        description=json.dumps(
                            {
                                "type": action_type,
                                "status": "executed",
                                "source_message_internal_id": inbound_internal_id,
                                "channel": channel_type,
                            },
                            ensure_ascii=False,
                        ),
                    ))
            fail_after("action")

            commercial = persist_commercial_turn_in_session(
                db,
                company_id,
                lead.id,
                channel_type,
                inbound_internal_id,
                internal_id,
                customer_text,
                assistant_text,
                decision,
                sales_snapshot,
                objection_snapshot,
                recommendation_decision,
            )
            if commercial.get("skipped") or not commercial.get("decision_id"):
                raise RuntimeError("canonical_commercial_persistence_rejected")
            fail_after("commercial")

            invalidate_prior_suggestions_for_inbound_message(
                db,
                company_id=company_id,
                lead_id=lead.id,
                inbound_message_internal_id=inbound_internal_id,
            )
            fail_after("invalidation")

            if trace:
                from services.pilot_telemetry_service import record_ai_trace, record_pilot_event

                record_ai_trace(
                    db,
                    company_id=company_id,
                    lead_id=lead.id,
                    trace=trace,
                    commit=False,
                )
                if channel_type == "VELOR_WEB_CHAT":
                    record_pilot_event(
                        db,
                        event_name="first_public_conversation",
                        company_id=company_id,
                        actor_type="customer",
                        entity_id=company_id,
                        source=telemetry_source,
                        metadata={"channel": channel_type, "source_message_id": inbound.id},
                        commit=False,
                    )
                record_pilot_event(
                    db,
                    event_name="customer_reply_generated",
                    company_id=company_id,
                    actor_type="system",
                    entity_id=internal_id,
                    source=telemetry_source,
                    metadata={
                        "channel": channel_type,
                        "response_path": trace.get("response_path"),
                        "plan_type": trace.get("response_plan_type"),
                    },
                    commit=False,
                )
                if trace.get("response_plan_type") == "PURCHASE_HANDOFF":
                    record_pilot_event(
                        db,
                        event_name="purchase_handoff_started",
                        company_id=company_id,
                        actor_type="customer",
                        entity_id=inbound_internal_id,
                        source=telemetry_source,
                        metadata={"channel": channel_type, "source_message_id": inbound.id},
                        commit=False,
                    )
            fail_after("telemetry")

            inbound.processing_status = "completed"
            inbound.processing_completed_at = datetime.now(timezone.utc)
            fail_after("claim_completion")
            db.commit()
            return {
                "internal_id": internal_id,
                "public_message_id": public_message_id,
                "lead_id": lead.id,
                "commercial": commercial,
            }
        except Exception:
            db.rollback()
            raise


def find_reply_for_inbound(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    inbound: Message,
) -> tuple[Optional[Message], Optional[Dict[str, Any]]]:
    """Resolve the canonical reply without guessing from message ordering."""
    reply = (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.user_id == user_id,
            Message.sender == "assistant",
            Message.direction == "outgoing",
            Message.in_reply_to_message_id == inbound.id,
        )
        .first()
    )

    response_envelope = None
    if reply is not None:
        event = (
            db.query(SystemEvent)
            .filter(
                SystemEvent.company_id == company_id,
                SystemEvent.event_type == "message.created",
                SystemEvent.entity_id == reply.internal_message_id,
            )
            .order_by(SystemEvent.id.desc())
            .first()
        )
        if event:
            try:
                payload = json.loads(event.payload or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload.get("response"), dict):
                response_envelope = payload["response"]
        return reply, response_envelope

    # Compatibility for pre-migration rows.  New writes always use the FK and
    # therefore cannot link a concurrent turn to the wrong response.
    events = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.company_id == company_id,
            SystemEvent.event_type == "message.created",
        )
        .order_by(SystemEvent.id.desc())
        .limit(250)
        .all()
    )
    for event in events:
        try:
            payload = json.loads(event.payload or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("in_reply_to") != inbound.internal_message_id:
            continue
        legacy_reply = (
            db.query(Message)
            .filter(
                Message.company_id == company_id,
                Message.user_id == user_id,
                Message.internal_message_id == event.entity_id,
                Message.sender == "assistant",
                Message.direction == "outgoing",
            )
            .first()
        )
        if legacy_reply:
            return (
                legacy_reply,
                payload.get("response")
                if isinstance(payload.get("response"), dict)
                else None,
            )
    return None, None
