"""Atomic, monotonic delivery-state updates for outbound messages.

WhatsApp QR acknowledgements and Meta delivery webhooks can arrive more than
once and out of order.  They can also be processed concurrently by different
workers.  This module keeps the persisted state monotonic while still allowing
a failed send to recover after a successful retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging

from sqlalchemy.exc import IntegrityError

from database import Message, MessageEvent, SystemEvent


logger = logging.getLogger("adam.message_delivery")

_PROGRESS_RANK = {
    "pending": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
}
_VALID_STATUSES = frozenset((*_PROGRESS_RANK, "failed"))


@dataclass(frozen=True)
class DeliveryUpdateResult:
    status_changed: bool
    provider_id_attached: bool
    final_status: str


def should_apply_delivery_transition(
    current_status: str | None,
    target_status: str | None,
) -> bool:
    """Return whether ``target_status`` advances the current delivery truth.

    ``failed`` is accepted from pending or sent because a provider may accept
    an API request and later report that it could not send the message.  It
    cannot overwrite delivered/read truth.  A later successful retry may
    recover a failed row to sent/delivered/read.  Forward jumps are valid
    because providers do not guarantee every intermediate callback reaches us.
    """

    current = str(current_status or "").strip().casefold()
    target = str(target_status or "").strip().casefold()
    if target not in _VALID_STATUSES or target == current:
        return False

    if current == "failed":
        return target in {"sent", "delivered", "read"}
    if target == "failed":
        return current not in {"failed", "delivered", "read"}
    if target == "pending":
        return current not in _VALID_STATUSES
    if current not in _PROGRESS_RANK:
        return True
    return _PROGRESS_RANK[target] > _PROGRESS_RANK[current]


def apply_message_delivery_update(
    db,
    message: Message,
    target_status: str,
    *,
    provider_message_id: str | None = None,
    event_timestamp: datetime | None = None,
    failure_reason: str | None = None,
    source: str | None = None,
    max_compare_and_set_attempts: int = 5,
) -> DeliveryUpdateResult:
    """Atomically update one message and append its observable state event.

    The conditional UPDATE prevents a worker with a stale ORM snapshot from
    overwriting a newer status.  On contention, the transition is reevaluated
    against the freshly committed state.
    """

    message_id = message.id
    target = str(target_status or "").strip().casefold()
    provider_id = str(provider_message_id).strip() if provider_message_id else None
    normalized_failure_reason = str(failure_reason or "").strip()[:200] or None
    normalized_source = str(source or "").strip()[:80] or None
    if target == "failed" and normalized_failure_reason is None:
        normalized_failure_reason = "provider_reported_failure"
    timestamp = event_timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    suppress_provider_id = False

    for _ in range(max(1, max_compare_and_set_attempts)):
        fresh = (
            db.query(Message)
            .populate_existing()
            .filter(Message.id == message_id)
            .first()
        )
        if fresh is None:
            return DeliveryUpdateResult(False, False, "")

        current_status = str(fresh.delivery_status or "").strip().casefold()
        status_changed = should_apply_delivery_transition(current_status, target)
        provider_id_attached = False
        replace_provider_id = False

        if provider_id and fresh.wa_message_id:
            replace_provider_id = bool(
                fresh.wa_message_id != provider_id
                and status_changed
                and current_status == "failed"
                and target in {"sent", "delivered", "read"}
            )
            if fresh.wa_message_id != provider_id and not replace_provider_id:
                logger.warning(
                    "Provider message id mismatch suppressed for internal message %s",
                    fresh.internal_message_id,
                )
        if (
            provider_id
            and (not fresh.wa_message_id or replace_provider_id)
            and not suppress_provider_id
        ):
            collision = (
                db.query(Message.id)
                .filter(
                    Message.wa_message_id == provider_id,
                    Message.id != message_id,
                )
                .first()
            )
            if collision is None:
                provider_id_attached = True
            else:
                suppress_provider_id = True
                logger.warning(
                    "Provider message id collision suppressed for internal message %s",
                    fresh.internal_message_id,
                )

        if not status_changed and not provider_id_attached:
            return DeliveryUpdateResult(False, False, fresh.delivery_status)

        values = {}
        query = db.query(Message).filter(Message.id == message_id)
        if status_changed:
            values[Message.delivery_status] = target
            query = query.filter(Message.delivery_status == fresh.delivery_status)
        if provider_id_attached:
            values[Message.wa_message_id] = provider_id
            if replace_provider_id:
                query = query.filter(
                    Message.wa_message_id == fresh.wa_message_id
                )
            else:
                query = query.filter(Message.wa_message_id.is_(None))

        try:
            updated = query.update(values, synchronize_session=False)
            if updated != 1:
                db.rollback()
                continue

            db.expire_all()
            updated_message = db.query(Message).filter(Message.id == message_id).one()
            if status_changed:
                db.add(
                    MessageEvent(
                        message_id=updated_message.id,
                        status=target,
                        timestamp=timestamp,
                    )
                )
                db.add(
                    SystemEvent(
                        company_id=updated_message.company_id,
                        event_type="message.updated",
                        entity_id=updated_message.internal_message_id,
                        payload=json.dumps(
                            {
                                "message_id": updated_message.internal_message_id,
                                "wa_message_id": updated_message.wa_message_id,
                                "sender": updated_message.sender,
                                "direction": updated_message.direction,
                                "text": updated_message.message,
                                "user_id": updated_message.user_id,
                                "delivery_status": updated_message.delivery_status,
                                **(
                                    {
                                        "failure_reason": normalized_failure_reason,
                                        "source": normalized_source or "delivery_update",
                                    }
                                    if target == "failed"
                                    else {}
                                ),
                                "timestamp": timestamp.isoformat(),
                            }
                        ),
                    )
                )
                if target == "failed":
                    db.add(
                        SystemEvent(
                            company_id=updated_message.company_id,
                            event_type="delivery.failed",
                            entity_id=updated_message.internal_message_id,
                            payload=json.dumps(
                                {
                                    "message_id": updated_message.internal_message_id,
                                    "delivery_status": "failed",
                                    "failure_reason": normalized_failure_reason,
                                    "source": normalized_source or "delivery_update",
                                    "timestamp": timestamp.isoformat(),
                                }
                            ),
                        )
                    )
            db.commit()
            return DeliveryUpdateResult(
                status_changed,
                provider_id_attached,
                updated_message.delivery_status,
            )
        except IntegrityError:
            # A different worker may have attached the same globally unique
            # provider id after our collision check.  Preserve the status
            # transition and retry without attempting to claim that id.
            db.rollback()
            suppress_provider_id = True

    db.expire_all()
    final = db.query(Message).filter(Message.id == message_id).first()
    return DeliveryUpdateResult(
        False,
        False,
        final.delivery_status if final is not None else "",
    )
