"""Bounded delivery reliability helpers for the canonical V2 path.

The outbound ``Message`` row is the durable delivery intent.  This module
adds the External API acknowledgement boundary and keeps provider failures
confined to delivery state; conversation and commercial state remain owned by
the already-committed V2 turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Optional

from database import Message, SystemEvent
from services.message_delivery import DeliveryUpdateResult, apply_message_delivery_update


EXTERNAL_API_ACK_ENDPOINT = "/api/external/delivery/ack"
EXTERNAL_API_ACK_STATUSES = frozenset({"sent", "delivered", "failed"})


@dataclass(frozen=True)
class ExternalDeliveryAckResult:
    outcome: str
    status: str
    internal_message_id: Optional[str] = None
    failure_reason: Optional[str] = None


def external_api_ack_contract() -> dict:
    """Return the stable, caller-facing acknowledgement contract."""
    return {
        "endpoint": EXTERNAL_API_ACK_ENDPOINT,
        "method": "POST",
        "statuses": ["sent", "delivered", "failed"],
        "initial_status": "pending",
    }


def _message_channel(db, message: Message) -> Optional[str]:
    event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.company_id == message.company_id,
            SystemEvent.event_type == "message.created",
            SystemEvent.entity_id == message.internal_message_id,
        )
        .order_by(SystemEvent.id.desc())
        .first()
    )
    if event is None:
        return None
    try:
        payload = json.loads(event.payload or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    channel = payload.get("channel")
    return str(channel).strip() if channel else None


def acknowledge_external_api_delivery(
    db,
    *,
    company_id: str,
    internal_message_id: str,
    status: str,
    failure_reason: Optional[str] = None,
    event_timestamp: Optional[datetime] = None,
) -> ExternalDeliveryAckResult:
    """Apply an authenticated, idempotent External API delivery acknowledgement.

    Only new canonical V2 outbound rows explicitly tagged ``EXTERNAL_API`` are
    eligible.  A duplicate or stale acknowledgement is accepted as a no-op;
    the monotonic transition helper prevents it from regressing delivered/read
    truth or attaching a provider identity to another message.
    """
    target = str(status or "").strip().casefold()
    if target not in EXTERNAL_API_ACK_STATUSES:
        raise ValueError("unsupported_delivery_status")
    clean_id = str(internal_message_id or "").strip()
    if not clean_id:
        raise ValueError("internal_message_id_required")

    message = (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.internal_message_id == clean_id,
            Message.direction == "outgoing",
            Message.sender == "assistant",
        )
        .first()
    )
    if message is None:
        return ExternalDeliveryAckResult("not_found", "unknown", clean_id)

    channel = _message_channel(db, message)
    if channel != "EXTERNAL_API":
        return ExternalDeliveryAckResult("not_external_api", message.delivery_status, clean_id)

    reason = str(failure_reason or "").strip()[:200] or None
    if target == "failed" and reason is None:
        reason = "external_provider_failed"
    result: DeliveryUpdateResult = apply_message_delivery_update(
        db,
        message,
        target,
        event_timestamp=event_timestamp,
        failure_reason=reason,
        source="external_api_ack",
    )
    return ExternalDeliveryAckResult(
        "applied" if result.status_changed else "duplicate_or_stale",
        result.final_status,
        clean_id,
        reason,
    )
