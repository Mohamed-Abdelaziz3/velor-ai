"""
sales_state_service.py — Canonical Sales State Intelligence & Buyer Intent Model
=================================================================================
Provides one canonical, evidence-backed, tenant-safe sales state and buyer intent model
for VELOR backend.

Key Principles:
1. Separate Primary Sales State from Buyer Intent.
2. Authority hierarchy: Fresh explicit customer behavior > recent customer events > memory summary.
   Assistant messages, company prompts, and sales tone have ZERO authority to set buyer state.
3. Bounded enums for state, intent, strength, confidence, momentum, and reason codes.
4. Hysteresis & state preservation for weak/ambiguous messages ("تمام", "شكرا", "اوكي").
5. Out-of-order and duplicate/retry idempotency.
6. Tenant isolation across all lookups.
7. Legacy adapters for temperature, status, stage, and conversation_state.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

log = logging.getLogger("adam.sales_state")

MODEL_VERSION = "velor_sales_state_v1"


class PrimarySalesState(str, Enum):
    UNKNOWN = "UNKNOWN"
    BROWSING = "BROWSING"
    NEED_DISCOVERY = "NEED_DISCOVERY"
    EVALUATING = "EVALUATING"
    COMPARING = "COMPARING"
    OBJECTING = "OBJECTING"
    NEGOTIATING = "NEGOTIATING"
    READY_TO_BUY = "READY_TO_BUY"
    COMMITTING = "COMMITTING"
    WON = "WON"
    STALLED = "STALLED"
    LOST = "LOST"


class BuyerIntent(str, Enum):
    GENERAL_INQUIRY = "GENERAL_INQUIRY"
    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    PRODUCT_INFORMATION = "PRODUCT_INFORMATION"
    PRICE_INQUIRY = "PRICE_INQUIRY"
    AVAILABILITY_CHECK = "AVAILABILITY_CHECK"
    PRODUCT_COMPARISON = "PRODUCT_COMPARISON"
    RECOMMENDATION_REQUEST = "RECOMMENDATION_REQUEST"
    BULK_PURCHASE = "BULK_PURCHASE"
    DISCOUNT_INQUIRY = "DISCOUNT_INQUIRY"
    NEGOTIATION = "NEGOTIATION"
    DELIVERY_INQUIRY = "DELIVERY_INQUIRY"
    PAYMENT_INQUIRY = "PAYMENT_INQUIRY"
    PURCHASE_COMMITMENT = "PURCHASE_COMMITMENT"
    ORDER_NEXT_STEP = "ORDER_NEXT_STEP"
    CANCELLATION_OR_REJECTION = "CANCELLATION_OR_REJECTION"
    PRICE_OBJECTION = "PRICE_OBJECTION"
    REACTIVATION = "REACTIVATION"
    SUPPORT_OR_POST_SALE = "SUPPORT_OR_POST_SALE"
    OTHER = "OTHER"


class IntentStrength(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Momentum(str, Enum):
    PROGRESSING = "PROGRESSING"
    STABLE = "STABLE"
    REGRESSING = "REGRESSING"
    UNKNOWN = "UNKNOWN"


class ReasonCode(str, Enum):
    EXPLICIT_PRICE_INQUIRY = "EXPLICIT_PRICE_INQUIRY"
    EXPLICIT_PRODUCT_EVALUATION = "EXPLICIT_PRODUCT_EVALUATION"
    EXPLICIT_COMPARISON = "EXPLICIT_COMPARISON"
    EXPLICIT_NEGOTIATION = "EXPLICIT_NEGOTIATION"
    EXPLICIT_PURCHASE_COMMITMENT = "EXPLICIT_PURCHASE_COMMITMENT"
    PAYMENT_NEXT_STEP_REQUEST = "PAYMENT_NEXT_STEP_REQUEST"
    EXPLICIT_REJECTION = "EXPLICIT_REJECTION"
    PRICE_OBJECTION = "PRICE_OBJECTION"
    REACTIVATED_AFTER_STALL = "REACTIVATED_AFTER_STALL"
    REACTIVATED_AFTER_LOST = "REACTIVATED_AFTER_LOST"
    WEAK_ACK_ONLY = "WEAK_ACK_ONLY"
    AMBIGUOUS_SIGNAL = "AMBIGUOUS_SIGNAL"
    GREETING_ONLY = "GREETING_ONLY"
    ORDER_CONFIRMATION_EVENT = "ORDER_CONFIRMATION_EVENT"
    DEFERRAL_EXPLICIT = "DEFERRAL_EXPLICIT"
    JUST_BROWSING_EXPLICIT = "JUST_BROWSING_EXPLICIT"
    AVAILABILITY_CHECK_EXPLICIT = "AVAILABILITY_CHECK_EXPLICIT"


_STATE_HIERARCHY: Dict[str, int] = {
    PrimarySalesState.UNKNOWN.value: 0,
    PrimarySalesState.LOST.value: 0,
    PrimarySalesState.BROWSING.value: 1,
    PrimarySalesState.NEED_DISCOVERY.value: 2,
    PrimarySalesState.STALLED.value: 2,
    PrimarySalesState.EVALUATING.value: 3,
    PrimarySalesState.COMPARING.value: 4,
    PrimarySalesState.OBJECTING.value: 4,
    PrimarySalesState.NEGOTIATING.value: 5,
    PrimarySalesState.READY_TO_BUY.value: 6,
    PrimarySalesState.COMMITTING.value: 7,
    PrimarySalesState.WON.value: 8,
}


@dataclass
class SalesStateSnapshot:
    company_id: str
    lead_id: Optional[int]
    conversation_id: Optional[str]
    primary_state: str
    buyer_intents: List[str]
    intent_strength: str
    confidence: float
    previous_state: Optional[str] = None
    transition: Optional[str] = None
    transition_event: Optional[str] = None
    momentum: str = Momentum.UNKNOWN.value
    evidence_refs: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_version: str = MODEL_VERSION

    def __post_init__(self):
        # Enforce bounds and schema contracts
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        valid_states = {s.value for s in PrimarySalesState}
        if self.primary_state not in valid_states:
            raise ValueError(f"Invalid primary_state: {self.primary_state}")

        valid_intents = {i.value for i in BuyerIntent}
        cleaned_intents = []
        for intent in self.buyer_intents:
            if intent in valid_intents:
                if intent not in cleaned_intents:
                    cleaned_intents.append(intent)
            else:
                log.warning("Rejected unknown buyer intent label: %s", intent)
        self.buyer_intents = cleaned_intents or [BuyerIntent.OTHER.value]

        if self.intent_strength not in {s.value for s in IntentStrength}:
            self.intent_strength = IntentStrength.LOW.value

        if self.momentum not in {m.value for m in Momentum}:
            self.momentum = Momentum.UNKNOWN.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SalesStateSnapshot":
        return cls(
            company_id=data.get("company_id", ""),
            lead_id=data.get("lead_id"),
            conversation_id=data.get("conversation_id"),
            primary_state=data.get("primary_state", PrimarySalesState.UNKNOWN.value),
            buyer_intents=data.get("buyer_intents", [BuyerIntent.GENERAL_INQUIRY.value]),
            intent_strength=data.get("intent_strength", IntentStrength.LOW.value),
            confidence=data.get("confidence", 0.5),
            previous_state=data.get("previous_state"),
            transition=data.get("transition"),
            transition_event=data.get("transition_event"),
            momentum=data.get("momentum", Momentum.UNKNOWN.value),
            evidence_refs=data.get("evidence_refs", []),
            reason_codes=data.get("reason_codes", []),
            observed_at=data.get("observed_at", datetime.now(timezone.utc).isoformat()),
            model_version=data.get("model_version", MODEL_VERSION),
        )

    def to_legacy_temperature(self) -> str:
        if self.primary_state in {PrimarySalesState.READY_TO_BUY.value, PrimarySalesState.COMMITTING.value, PrimarySalesState.WON.value}:
            return "hot"
        if self.primary_state in {PrimarySalesState.EVALUATING.value, PrimarySalesState.COMPARING.value, PrimarySalesState.NEGOTIATING.value, PrimarySalesState.OBJECTING.value}:
            return "warm"
        return "cold"

    def to_legacy_status(self) -> str:
        if self.primary_state == PrimarySalesState.WON.value:
            return "won"
        if self.primary_state == PrimarySalesState.LOST.value:
            return "lost"
        if self.primary_state in {PrimarySalesState.COMMITTING.value, PrimarySalesState.READY_TO_BUY.value}:
            return "hot_lead"
        if self.primary_state in {PrimarySalesState.EVALUATING.value, PrimarySalesState.COMPARING.value, PrimarySalesState.NEGOTIATING.value, PrimarySalesState.OBJECTING.value}:
            return "qualified"
        return "new"

    def to_legacy_stage(self) -> str:
        if self.primary_state == PrimarySalesState.WON.value:
            return "Won"
        if self.primary_state == PrimarySalesState.LOST.value:
            return "Lost"
        if self.primary_state in {PrimarySalesState.READY_TO_BUY.value, PrimarySalesState.COMMITTING.value}:
            return "Closing"
        if self.primary_state in {PrimarySalesState.EVALUATING.value, PrimarySalesState.COMPARING.value, PrimarySalesState.NEGOTIATING.value, PrimarySalesState.OBJECTING.value}:
            return "Evaluating"
        return "Information Gathering"

    def to_legacy_conversation_state(self) -> str:
        if self.primary_state in {PrimarySalesState.READY_TO_BUY.value, PrimarySalesState.COMMITTING.value}:
            return "CLOSING"
        if self.primary_state == PrimarySalesState.OBJECTING.value:
            return "OBJECTION_HANDLING"
        if self.primary_state in {PrimarySalesState.BROWSING.value, PrimarySalesState.NEED_DISCOVERY.value, PrimarySalesState.UNKNOWN.value}:
            return "GREETING"
        return "QUALIFICATION"


def _normalize_text(text: str) -> str:
    cleaned = str(text or "").strip()
    return re.sub(r"\s+", " ", cleaned)


def _fold_arabic(value: str) -> str:
    text = _normalize_text(value).casefold()
    text = re.sub(r"[إأآا]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    return text


def _strip_punctuation(value: str) -> str:
    folded = _fold_arabic(value)
    text = re.sub(r"[؟?!.,،؛:()[\]{}\"']", " ", folded)
    return re.sub(r"\s+", " ", text).strip()


def _is_greeting_only(text: str) -> bool:
    compact = _strip_punctuation(text)
    if not compact:
        return False
    without = re.sub(
        r"\b(السلام عليكم|وعليكم السلام|سلام عليكم|سلام|مرحبا|اهلا|هلا|هاي|صباح الخير|مساء الخير|ازيك|عامل ايه|hello|hi|hey)\b",
        "",
        compact,
        flags=re.I,
    ).strip()
    return len(without) <= 2 and len(compact.split()) <= 4


def _is_weak_ack(text: str) -> bool:
    compact = _strip_punctuation(text)
    if not compact:
        return False
    weak_tokens = {"تمام", "شكرا", "شكرا لك", "ماشي", "اوكي", "أوكي", "ربنا يخليك", "تسلم", "ok", "thanks", "thank you", "k"}
    return compact in weak_tokens or (len(compact.split()) <= 2 and any(t in compact for t in ["تمام", "شكرا", "ماشي", "اوكي", "thanks"]))


def _matches_any(text: str, patterns: List[str]) -> bool:
    folded = _fold_arabic(text)
    return any(re.search(p, folded, re.I) for p in patterns)


def _extract_arabic_indic_digit(text: str) -> Optional[int]:
    indic_map = {"٠": 0, "١": 1, "٢": 2, "٣": 3, "٤": 4, "٥": 5, "٦": 6, "٧": 7, "٨": 8, "٩": 9}
    converted = ""
    for char in text:
        if char in indic_map:
            converted += str(indic_map[char])
        elif char.isdigit():
            converted += char
    if converted and converted.isdigit():
        return int(converted)
    return None


def evaluate_sales_state(
    db: Session,
    company_id: str,
    lead_id: Optional[int],
    current_message_text: str,
    current_message_id: Optional[str] = None,
    current_message_timestamp: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None,
    *,
    persist: bool = True,
) -> SalesStateSnapshot:
    """
    Main entry point for Sales State Intelligence evaluation.
    Evaluates customer behavior, existing lead state, and transitions deterministically.
    """
    from database import Lead, LeadEvidence, Message

    # 1. Fetch lead & existing state (Tenant isolated)
    lead: Optional[Lead] = None
    previous_snapshot: Optional[SalesStateSnapshot] = None
    previous_state = PrimarySalesState.UNKNOWN.value

    if lead_id:
        lead = db.query(Lead).filter(Lead.company_id == company_id, Lead.id == lead_id, Lead.is_deleted == False).first()
        if lead and getattr(lead, "sales_state_snapshot", None):
            try:
                raw_snap = json.loads(lead.sales_state_snapshot)
                previous_snapshot = SalesStateSnapshot.from_dict(raw_snap)
                previous_state = previous_snapshot.primary_state
            except Exception as e:
                log.warning("Failed to parse existing sales_state_snapshot for lead_id=%s: %s", lead_id, e)

    # 2. Out-of-order check
    if previous_snapshot and current_message_timestamp and previous_snapshot.observed_at:
        try:
            prev_dt = datetime.fromisoformat(previous_snapshot.observed_at)
            if current_message_timestamp.tzinfo is None:
                current_message_timestamp = current_message_timestamp.replace(tzinfo=timezone.utc)
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=timezone.utc)

            if current_message_timestamp < prev_dt and previous_state in {PrimarySalesState.COMMITTING.value, PrimarySalesState.WON.value}:
                log.info("Out-of-order message detected for lead_id=%s. Preserving advanced previous state.", lead_id)
                return previous_snapshot
        except Exception as exc:
            log.warning("Timestamp parsing exception during out-of-order check: %s", exc)

    # 3. Clean and normalize current customer text
    raw_text = current_message_text or ""
    folded_text = _fold_arabic(raw_text)

    # Verify evidence refs tenant safety
    safe_evidence_refs = []
    for ref in evidence_refs or []:
        if ref.startswith("tenant:") and not ref.startswith(f"tenant:{company_id}:"):
            log.warning("Cross-tenant evidence ref rejected: %s", ref)
            continue
        safe_evidence_refs.append(ref)

    if current_message_id and f"msg:{current_message_id}" not in safe_evidence_refs:
        safe_evidence_refs.append(f"msg:{current_message_id}")

    # 4. Pattern matching on fresh customer text
    is_rejection = _matches_any(
        raw_text,
        [
            r"مش\s+مهتم",
            r"مش\s+عايز",
            r"مش\s+عاوز",
            r"مش\s+هشتري",
            r"مش\s+هكفي",
            r"خلاص\s+مش",
            r"خلاص\s+مفيش",
            r"الغاء",
            r"إلغاء",
            r"not\s+interested",
            r"don'?t\s+want",
            r"cancel\s+order",
        ],
    )

    is_payment_commitment = _matches_any(
        raw_text,
        [
            r"ابعتلي\s+رقم\s+الدفع",
            r"ارسل\s+رقم\s+الدفع",
            r"ابعثلي\s+رقم\s+الدفع",
            r"ابعث\s+رقم\s+الدفع",
            r"رقم\s+الحساب",
            r"رقم\s+الكارت",
            r"احول\s+فين",
            r"أحول\s+فين",
            r"أحول\s+على\s+رقم\s+إيه",
            r"احول\s+على\s+رقم\s+ايه",
            r"انقل\s+الفلوس\s+فين",
            r"send\s+(me\s+)?payment\s+(link|number|details)",
            r"where\s+do\s+i\s+pay",
            r"how\s+to\s+pay",
            r"هحول\s+دلوقتي",
            r"تمام\s+هات\s+واحد",
            r"عايز\s+اتنين",
            r"عايز\s+[٠-٩0-9]+",
            r"اريد\s+[٠-٩0-9]+",
            r"أطلب\s+إزاي",
            r"اطلب\s+ازاي",
            r"خلاص\s+هطلب",
            r"عايز\s+أشترك",
            r"عايز\s+اشترك",
        ],
    )

    is_price_objection = _matches_any(
        raw_text,
        [
            r"\bغالي\b",
            r"\bغالية\b",
            r"السعر\s+عالي",
            r"السعر\s+مرتفع",
            r"مكلف",
            r"\bexpensive\b",
            r"too\s+much",
        ],
    )

    is_negotiation = _matches_any(
        raw_text,
        [
            r"آخر\s+سعر",
            r"اخر\s+سعر",
            r"لو\s+خدت\s+\d+",
            r"لو\s+خدت\s+[٠-٩]+",
            r"لو\s+خدت\s+كمية",
            r"خصم",
            r"discount",
            r"best\s+price",
        ],
    )

    is_comparison = _matches_any(
        raw_text,
        [
            r"قارنلي",
            r"قارن\s+بين",
            r"ايه\s+الفرق",
            r"إيه\s+الفرق",
            r"فرق\s+بين",
            r"مقارنة",
            r"compare",
            r"difference\s+between",
        ],
    )

    is_price_inquiry = _matches_any(
        raw_text,
        [
            r"بكام",
            r"\bكام\b",
            r"السعر",
            r"اسعار",
            r"أسعار",
            r"التكلفة",
            r"تكلفة",
            r"\bprice\b",
            r"\bcost\b",
            r"how\s+much",
        ],
    )

    is_availability_check = _matches_any(
        raw_text,
        [
            r"متوفر",
            r"موجود",
            r"عندكم",
            r"available",
            r"in\s+stock",
        ],
    )

    is_deferral = _matches_any(
        raw_text,
        [
            r"هفكر",
            r"افكر",
            r"أفكر",
            r"مش\s+دلوقتي",
            r"بعدين",
            r"ارجعلك",
            r"think\s+about",
            r"not\s+now",
            r"later",
        ],
    )

    is_just_browsing = _matches_any(
        raw_text,
        [
            r"بسأل",
            r"بتفرج",
            r"أنا\s+بس",
            r"انا\s+بس",
            r"just\s+asking",
            r"just\s+browsing",
        ],
    )

    is_reactivation_inquiry = _matches_any(
        raw_text,
        [
            r"لسه\s+العرض\s+موجود",
            r"رجعت\s+أفكر",
            r"رجعت\s+افكر",
            r"كنت\s+سألتك",
            r"is\s+the\s+offer\s+still\s+available",
            r"came\s+back",
        ],
    )

    # 5. Evaluate Primary State & Buyer Intents
    new_state = PrimarySalesState.UNKNOWN.value
    buyer_intents: List[str] = []
    reason_codes: List[str] = []
    intent_strength = IntentStrength.LOW.value
    confidence = 0.5
    transition_event: Optional[str] = None

    # Handle Reactivation check
    if (previous_state in {PrimarySalesState.STALLED.value, PrimarySalesState.LOST.value}) and (
        is_reactivation_inquiry or is_price_inquiry or is_availability_check or is_comparison or is_payment_commitment
    ):
        transition_event = "REACTIVATED"
        if previous_state == PrimarySalesState.STALLED.value:
            reason_codes.append(ReasonCode.REACTIVATED_AFTER_STALL.value)
        else:
            reason_codes.append(ReasonCode.REACTIVATED_AFTER_LOST.value)

    if is_rejection:
        new_state = PrimarySalesState.LOST.value
        buyer_intents.append(BuyerIntent.CANCELLATION_OR_REJECTION.value)
        reason_codes.append(ReasonCode.EXPLICIT_REJECTION.value)
        intent_strength = IntentStrength.HIGH.value
        confidence = 0.95

    elif is_payment_commitment:
        new_state = PrimarySalesState.COMMITTING.value
        buyer_intents.append(BuyerIntent.PAYMENT_INQUIRY.value)
        buyer_intents.append(BuyerIntent.PURCHASE_COMMITMENT.value)
        reason_codes.append(ReasonCode.EXPLICIT_PURCHASE_COMMITMENT.value)
        reason_codes.append(ReasonCode.PAYMENT_NEXT_STEP_REQUEST.value)
        intent_strength = IntentStrength.HIGH.value
        confidence = 0.92

        if is_price_objection:
            buyer_intents.append(BuyerIntent.PRICE_OBJECTION.value if hasattr(BuyerIntent, "PRICE_OBJECTION") else BuyerIntent.NEGOTIATION.value)
            reason_codes.append(ReasonCode.PRICE_OBJECTION.value)

    elif is_negotiation:
        new_state = PrimarySalesState.NEGOTIATING.value
        buyer_intents.append(BuyerIntent.NEGOTIATION.value)
        reason_codes.append(ReasonCode.EXPLICIT_NEGOTIATION.value)
        if "خصم" in raw_text or "discount" in raw_text.lower():
            buyer_intents.append(BuyerIntent.DISCOUNT_INQUIRY.value)
        if re.search(r"(\d+|[٠-٩]+)", raw_text):
            buyer_intents.append(BuyerIntent.BULK_PURCHASE.value)
        intent_strength = IntentStrength.HIGH.value if (BuyerIntent.BULK_PURCHASE.value in buyer_intents) else IntentStrength.MEDIUM.value
        confidence = 0.88

    elif is_comparison:
        new_state = PrimarySalesState.COMPARING.value
        buyer_intents.append(BuyerIntent.PRODUCT_COMPARISON.value)
        reason_codes.append(ReasonCode.EXPLICIT_COMPARISON.value)
        intent_strength = IntentStrength.MEDIUM.value
        confidence = 0.90

    elif is_price_objection:
        new_state = PrimarySalesState.OBJECTING.value
        buyer_intents.append(BuyerIntent.PRICE_OBJECTION.value)
        reason_codes.append(ReasonCode.PRICE_OBJECTION.value)
        intent_strength = IntentStrength.MEDIUM.value
        confidence = 0.85

    elif is_price_inquiry or is_availability_check:
        new_state = PrimarySalesState.EVALUATING.value
        if is_price_inquiry:
            buyer_intents.append(BuyerIntent.PRICE_INQUIRY.value)
            reason_codes.append(ReasonCode.EXPLICIT_PRICE_INQUIRY.value)
        if is_availability_check:
            buyer_intents.append(BuyerIntent.AVAILABILITY_CHECK.value)
            reason_codes.append(ReasonCode.AVAILABILITY_CHECK_EXPLICIT.value)

        # Higher intent strength if product name or quantity is present
        if len(raw_text.split()) > 2 and not is_just_browsing:
            intent_strength = IntentStrength.MEDIUM.value
            confidence = 0.85
        else:
            intent_strength = IntentStrength.LOW.value
            confidence = 0.80

        if is_just_browsing:
            reason_codes.append(ReasonCode.JUST_BROWSING_EXPLICIT.value)
            intent_strength = IntentStrength.LOW.value
            confidence = 0.90  # Confident that buyer is just browsing

    elif is_deferral:
        new_state = PrimarySalesState.STALLED.value
        buyer_intents.append(BuyerIntent.GENERAL_INQUIRY.value)
        reason_codes.append(ReasonCode.DEFERRAL_EXPLICIT.value)
        intent_strength = IntentStrength.LOW.value
        confidence = 0.80

    elif is_just_browsing:
        new_state = PrimarySalesState.BROWSING.value
        buyer_intents.append(BuyerIntent.PRODUCT_DISCOVERY.value)
        reason_codes.append(ReasonCode.JUST_BROWSING_EXPLICIT.value)
        intent_strength = IntentStrength.LOW.value
        confidence = 0.90

    elif _is_greeting_only(raw_text):
        new_state = previous_state if previous_state != PrimarySalesState.UNKNOWN.value else PrimarySalesState.BROWSING.value
        buyer_intents.append(BuyerIntent.GENERAL_INQUIRY.value)
        reason_codes.append(ReasonCode.GREETING_ONLY.value)
        intent_strength = IntentStrength.LOW.value
        confidence = 0.60

    elif _is_weak_ack(raw_text):
        # Weak ACK preserves prior state unless previous was UNKNOWN
        new_state = previous_state if previous_state != PrimarySalesState.UNKNOWN.value else PrimarySalesState.BROWSING.value
        buyer_intents.append(BuyerIntent.GENERAL_INQUIRY.value)
        reason_codes.append(ReasonCode.WEAK_ACK_ONLY.value)
        intent_strength = IntentStrength.LOW.value
        confidence = 0.70

    else:
        # Ambiguous message
        new_state = previous_state if previous_state != PrimarySalesState.UNKNOWN.value else PrimarySalesState.BROWSING.value
        buyer_intents.append(BuyerIntent.GENERAL_INQUIRY.value)
        reason_codes.append(ReasonCode.AMBIGUOUS_SIGNAL.value)
        intent_strength = IntentStrength.LOW.value
        confidence = 0.40

    # Fallback default intent if none set
    if not buyer_intents:
        buyer_intents.append(BuyerIntent.GENERAL_INQUIRY.value)

    # 6. Calculate Momentum
    prev_level = _STATE_HIERARCHY.get(previous_state, 0)
    new_level = _STATE_HIERARCHY.get(new_state, 0)

    if transition_event == "REACTIVATED":
        momentum = Momentum.PROGRESSING.value
    elif new_level > prev_level:
        momentum = Momentum.PROGRESSING.value
    elif new_level < prev_level:
        momentum = Momentum.REGRESSING.value
    else:
        momentum = Momentum.STABLE.value

    transition = f"{previous_state}_TO_{new_state}" if previous_state != new_state else "NONE"

    snapshot = SalesStateSnapshot(
        company_id=company_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        primary_state=new_state,
        buyer_intents=buyer_intents,
        intent_strength=intent_strength,
        confidence=confidence,
        previous_state=previous_state,
        transition=transition,
        transition_event=transition_event,
        momentum=momentum,
        evidence_refs=safe_evidence_refs,
        reason_codes=reason_codes,
        observed_at=datetime.now(timezone.utc).isoformat(),
        model_version=MODEL_VERSION,
    )

    # 7. Legacy callers may still request a state projection on the lead.
    # Public-turn V2 evaluation passes ``persist=False`` so this classifier is
    # a pure snapshot producer until the one public-turn transaction applies
    # its bounded delta.  In particular, do not let an intermediate helper
    # commit or refresh the session while a reply may still fail verification.
    if lead and persist:
        try:
            snapshot_json = json.dumps(snapshot.to_dict())
            setattr(lead, "sales_state_snapshot", snapshot_json)
            # Align legacy fields using adapters
            lead.temperature = snapshot.to_legacy_temperature()
            lead.status = snapshot.to_legacy_status()
            lead.stage = snapshot.to_legacy_stage()
            lead.conversation_state = snapshot.to_legacy_conversation_state()
            lead.intent_score = float(snapshot.confidence)
            lead.is_hot_deal = bool(snapshot.primary_state in {PrimarySalesState.READY_TO_BUY.value, PrimarySalesState.COMMITTING.value})
            lead.stage_updated_at = datetime.now(timezone.utc)
            db.add(lead)
            db.commit()
            db.refresh(lead)
        except Exception as err:
            db.rollback()
            log.error("Failed to update Lead sales_state_snapshot: %s", err)

    return snapshot
