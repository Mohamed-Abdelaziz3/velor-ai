import enum
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from database import (
    Lead,
    Message,
    MessageEvent,
    SystemEvent,
    _upsert_usage_in_session,
    get_phone_variants,
    normalize_whatsapp_number,
)

logger = logging.getLogger("adam.processing_claim")

STALE_CLAIM_TIMEOUT_SECONDS = int(os.getenv("STALE_CLAIM_TIMEOUT_SECONDS", "120"))


class ClaimResult(str, enum.Enum):
    CLAIM_ACQUIRED = "CLAIM_ACQUIRED"
    ALREADY_PROCESSING = "ALREADY_PROCESSING"
    COMPLETED = "COMPLETED"
    INTENTIONALLY_SKIPPED = "INTENTIONALLY_SKIPPED"
    RETRYABLE_RECLAIMED = "RETRYABLE_RECLAIMED"
    UNKNOWN_UNSAFE = "UNKNOWN_UNSAFE"


class DomainProcessingConflictError(Exception):
    """Raised when a processing claim conflict occurs in domain operations."""

    pass


def acquire_inbound_processing_claim(
    db: Session,
    company_id: str,
    user_id: str,
    wa_message_id: Optional[str],
    message_text: str,
    *,
    defer_side_effects: bool = False,
    commit: bool = True,
) -> Tuple[ClaimResult, Optional[Message]]:
    """
    Establishes atomic processing ownership for an inbound WhatsApp message identified by wa_message_id.

    Guarantees:
    - Exactly one worker owns processing of a logical turn at a time.
    - DB uniqueness IntegrityError on duplicate insertion is caught and classified internally (never leaks to AI fallback).
    - Crashed/abandoned processing attempts (started > STALE_CLAIM_TIMEOUT_SECONDS ago) can be reclaimed atomically.
    - Completed or intentionally skipped attempts remain suppressed.
    """
    if not wa_message_id:
        return ClaimResult.CLAIM_ACQUIRED, None

    # Step 1: Check existing incoming message
    existing = (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.wa_message_id == wa_message_id,
            Message.direction == "incoming",
        )
        .first()
    )

    now = datetime.now(timezone.utc)

    if existing is None:
        # Try atomic insertion
        try:
            internal_id = str(uuid.uuid4())
            inc_msg = Message(
                internal_message_id=internal_id,
                public_message_id=f"pub-{uuid.uuid4().hex}",
                wa_message_id=wa_message_id,
                company_id=company_id,
                user_id=user_id,
                sender="user",
                direction="incoming",
                message=message_text,
                delivery_status="received",
                processing_status="processing",
                processing_started_at=now,
                processing_attempts=1,
            )
            db.add(inc_msg)
            db.flush()

            if not defer_side_effects:
                # Legacy paths project inbound telemetry immediately.  V2 uses
                # a lightweight durable lease here and stages these effects in
                # its final public-turn transaction instead.
                db.add(MessageEvent(message_id=inc_msg.id, status="received"))
                import json

                event_payload = json.dumps(
                    {
                        "message_id": internal_id,
                        "wa_message_id": wa_message_id,
                        "sender": "user",
                        "direction": "incoming",
                        "text": message_text,
                        "user_id": user_id,
                        "delivery_status": "received",
                        "timestamp": now.isoformat(),
                    }
                )
                db.add(
                    SystemEvent(
                        company_id=company_id,
                        event_type="message.created",
                        entity_id=internal_id,
                        payload=event_payload,
                    )
                )
                db.add(
                    SystemEvent(
                        company_id=company_id,
                        event_type="message.received",
                        entity_id=internal_id,
                        payload=event_payload,
                    )
                )

                base_phone = normalize_whatsapp_number(user_id)
                lead = (
                    db.query(Lead)
                    .filter(
                        Lead.company_id == company_id,
                        (Lead.whatsapp_number == base_phone) |
                        (Lead.phone.in_(get_phone_variants(base_phone))) |
                        (Lead.external_customer_id == user_id),
                        Lead.is_deleted == False,
                    )
                    .first()
                )
                if lead:
                    lead.last_message = message_text
                    lead.last_message_sender = "user"
                    lead.conversation_count = (lead.conversation_count or 0) + 1
                    lead.last_contact_date = func.now()

                try:
                    from services.evidence_engine import persist_evidence_for_message

                    persist_evidence_for_message(db, inc_msg)
                except Exception as evidence_exc:
                    logger.exception("Evidence extraction failed for message %s: %s", internal_id, evidence_exc)

                _upsert_usage_in_session(db, company_id, messages=1, requests=1)

            # V2 keeps its bare idempotency lease in the caller's open
            # transaction.  The final turn executor is then the sole commit
            # boundary for the inbound row and every observable side effect.
            if commit:
                db.commit()
                db.refresh(inc_msg)
            else:
                db.flush()

            if not defer_side_effects:
                try:
                    from engine.intelligence_bus import bus, IntelligenceEvent, EventSeverity

                    bus.publish_sync(
                        IntelligenceEvent(
                            topic="message.received",
                            severity=EventSeverity.INFO,
                            company_id=company_id,
                            payload={
                                "message_id": internal_id,
                                "sender": "user",
                                "text": message_text,
                                "user_id": user_id,
                            },
                        )
                    )
                except Exception as bus_exc:
                    logger.warning("Intelligence bus publish failed for message %s: %s", internal_id, bus_exc)

            logger.info("Claim acquired for message %s (internal_id=%s)", wa_message_id, internal_id)
            return ClaimResult.CLAIM_ACQUIRED, inc_msg

        except IntegrityError:
            db.rollback()
            logger.info("IntegrityError on inserting claim for %s; re-querying existing row", wa_message_id)
            existing = (
                db.query(Message)
                .filter(
                    Message.company_id == company_id,
                    Message.wa_message_id == wa_message_id,
                    Message.direction == "incoming",
                )
                .first()
            )
            if not existing:
                # Unrelated IntegrityError (not a duplicate wa_message_id conflict) — do NOT swallow as duplicate claim
                logger.error("Unrelated IntegrityError during claim acquisition for wa_message_id=%s", wa_message_id)
                raise
            if existing.company_id != company_id:
                logger.info("Message %s already claimed by company %s", wa_message_id, existing.company_id)
                return ClaimResult.ALREADY_PROCESSING, existing

    # Step 2: Evaluate existing incoming claim status
    status = getattr(existing, "processing_status", "completed") or "completed"

    if status == "completed":
        return ClaimResult.COMPLETED, existing

    if status in ("skipped", "intentionally_skipped"):
        return ClaimResult.INTENTIONALLY_SKIPPED, existing

    if status in ("processing", "failed"):
        # Check if active vs stale/abandoned
        started_at = existing.processing_started_at
        is_stale = False
        if started_at is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed = (now - started_at).total_seconds()
            if elapsed >= STALE_CLAIM_TIMEOUT_SECONDS:
                is_stale = True
        else:
            is_stale = True

        if status == "processing" and not is_stale:
            logger.info(
                "Message %s is actively processing by another worker",
                wa_message_id,
            )
            return ClaimResult.ALREADY_PROCESSING, existing

        # Attempt atomic reclaim for failed or stale processing attempts
        reclaimed_count = (
            db.query(Message)
            .filter(
                Message.id == existing.id,
                Message.processing_status.in_(["processing", "failed"]),
                Message.processing_started_at == existing.processing_started_at,
            )
            .update(
                {
                    Message.processing_status: "processing",
                    Message.processing_started_at: now,
                    Message.processing_attempts: Message.processing_attempts + 1,
                },
                synchronize_session=False,
            )
        )
        if commit:
            db.commit()
        else:
            db.flush()

        if reclaimed_count == 1:
            db.refresh(existing)
            logger.info(
                "Atomically reclaimed processing claim for message %s (attempts=%d)",
                wa_message_id,
                existing.processing_attempts,
            )
            return ClaimResult.RETRYABLE_RECLAIMED, existing
        else:
            logger.info("Lost atomic reclaim race for message %s", wa_message_id)
            return ClaimResult.ALREADY_PROCESSING, existing

    return ClaimResult.COMPLETED, existing


def is_inbound_processing_claim_current(
    db: Session,
    internal_message_id: str,
    expected_attempts: Optional[int],
) -> bool:
    """
    Returns True only while the exact inbound processing attempt still owns the claim.

    This is a commit fence for timed-out requests: asyncio cancellation does not stop
    already-running thread work, so stale workers must re-check ownership before
    persisting assistant replies or intelligence updates.
    """
    if not internal_message_id or expected_attempts is None:
        return True

    msg = db.query(Message).filter(Message.internal_message_id == internal_message_id).first()
    return bool(
        msg
        and msg.processing_status == "processing"
        and msg.processing_attempts == expected_attempts
    )


def finalize_inbound_processing_claim(
    db: Session,
    internal_message_id: str,
    status: str,
    expected_attempts: Optional[int] = None,
) -> bool:
    """
    Finalizes an inbound processing claim state ('completed', 'skipped', 'failed').
    """
    if not internal_message_id:
        return False

    if expected_attempts is not None:
        updated = (
            db.query(Message)
            .filter(
                Message.internal_message_id == internal_message_id,
                Message.processing_status == "processing",
                Message.processing_attempts == expected_attempts,
            )
            .update(
                {
                    Message.processing_status: status,
                    Message.processing_completed_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if updated == 1:
            return True
        logger.warning(
            "Suppressed stale processing claim finalization for message %s (expected_attempt=%s, target_status=%s)",
            internal_message_id,
            expected_attempts,
            status,
        )
        return False

    msg = db.query(Message).filter(Message.internal_message_id == internal_message_id).first()
    if msg:
        msg.processing_status = status
        msg.processing_completed_at = datetime.now(timezone.utc)
        db.commit()
        return True
    return False
