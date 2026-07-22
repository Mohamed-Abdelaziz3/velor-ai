"""Provider-neutral admission contract for future trusted commercial outcomes.

This module deliberately does not infer an order or payment from chat.  A
provider adapter must authenticate its own payload, then pass the normalized
record through this boundary before a future persistence integration may label
an outcome ``CONFIRMED_ORDER`` or ``PAID``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Literal, Optional


TrustedOutcomeType = Literal["CONFIRMED_ORDER", "PAID"]
TRUSTED_PROVIDER_PROVENANCE_PREFIX = "provider_verified:"


class UntrustedOutcomeError(ValueError):
    """Raised when an outcome does not have authenticated provider authority."""


@dataclass(frozen=True)
class TrustedOutcome:
    company_id: str
    lead_id: int
    lead_binding_method: str
    outcome_type: TrustedOutcomeType
    provider: str
    provider_event_id: str
    provider_object_id: str
    idempotency_key: str
    occurred_at: datetime
    received_at: datetime
    verified_at: datetime
    signature_verified: bool
    raw_payload_hash: str
    provenance: str
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    reversal_of_provider_event_id: Optional[str] = None
    refund_amount: Optional[Decimal] = None
    refund_currency: Optional[str] = None


def is_trusted_outcome_provenance(provenance: str) -> bool:
    return str(provenance or "").strip().casefold().startswith(TRUSTED_PROVIDER_PROVENANCE_PREFIX)


def validate_trusted_outcome(
    outcome: TrustedOutcome,
    *,
    adapter_signature_verified: bool,
    provenance: str,
) -> TrustedOutcome:
    """Validate authority without making any network or persistence decision."""
    if provenance.strip().casefold() in {
        "chat",
        "conversation",
        "llm",
        "model",
        "heuristic",
        "deterministic_conversation",
        "deterministic_v1",
    }:
        raise UntrustedOutcomeError("conversation evidence cannot prove an order or payment")
    if not is_trusted_outcome_provenance(provenance):
        raise UntrustedOutcomeError("outcome provenance is not an admitted provider adapter")
    if outcome.provenance.strip().casefold() != provenance.strip().casefold():
        raise UntrustedOutcomeError("normalized provenance does not match adapter provenance")
    admitted_provider = provenance.split(":", 1)[1].strip().casefold()
    if admitted_provider != outcome.provider.strip().casefold():
        raise UntrustedOutcomeError("provider provenance does not match the normalized outcome")
    if not adapter_signature_verified or outcome.signature_verified is not True:
        raise UntrustedOutcomeError("provider authenticity was not verified")
    if not outcome.company_id or outcome.lead_id <= 0:
        raise UntrustedOutcomeError("tenant and lead authority are required")
    if not outcome.lead_binding_method.strip():
        raise UntrustedOutcomeError("an explicit lead binding method is required")
    if not outcome.provider.strip() or not outcome.provider_event_id.strip() or not outcome.provider_object_id.strip():
        raise UntrustedOutcomeError("provider identity and immutable references are required")
    if not outcome.idempotency_key.strip():
        raise UntrustedOutcomeError("an idempotency key is required")
    timestamps = {
        "occurred_at": outcome.occurred_at,
        "received_at": outcome.received_at,
        "verified_at": outcome.verified_at,
    }
    for name, value in timestamps.items():
        if value.tzinfo is None:
            raise UntrustedOutcomeError(f"{name} must be timezone-aware")
    occurred_at = outcome.occurred_at.astimezone(timezone.utc)
    received_at = outcome.received_at.astimezone(timezone.utc)
    verified_at = outcome.verified_at.astimezone(timezone.utc)
    if occurred_at > received_at or received_at > verified_at:
        raise UntrustedOutcomeError("outcome timestamps must be ordered occurred, received, verified")
    if verified_at > datetime.now(timezone.utc):
        raise UntrustedOutcomeError("verified_at cannot be in the future")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", outcome.raw_payload_hash.strip()):
        raise UntrustedOutcomeError("raw_payload_hash must be a SHA-256 hex digest")
    if outcome.outcome_type == "CONFIRMED_ORDER" and not outcome.order_id:
        raise UntrustedOutcomeError("confirmed orders require an authoritative order_id")
    if outcome.outcome_type == "PAID" and not outcome.payment_id:
        raise UntrustedOutcomeError("paid outcomes require an authoritative payment_id")
    if (outcome.amount is None) != (outcome.currency is None):
        raise UntrustedOutcomeError("amount and currency must be supplied together")
    if outcome.amount is not None and outcome.amount < 0:
        raise UntrustedOutcomeError("amount cannot be negative")
    if (outcome.refund_amount is None) != (outcome.refund_currency is None):
        raise UntrustedOutcomeError("refund amount and currency must be supplied together")
    if outcome.refund_amount is not None:
        if not outcome.reversal_of_provider_event_id:
            raise UntrustedOutcomeError("refunds require a provider reversal reference")
        if outcome.refund_amount < 0:
            raise UntrustedOutcomeError("refund amount cannot be negative")
        if outcome.currency and outcome.refund_currency != outcome.currency:
            raise UntrustedOutcomeError("refund currency must match the outcome currency")
    return outcome
