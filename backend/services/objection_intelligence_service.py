"""
objection_intelligence_service.py — Objection Intelligence & Ethical Response Strategy
=======================================================================================
Provides one canonical, tenant-safe, evidence-backed Objection Intelligence and Ethical
Response Strategy subsystem for VELOR backend.

Key Principles:
1. Separate Objection Type from Sales State, Buyer Intent, and Next Best Action.
2. Authority hierarchy:
   Highest authority:
     - Fresh explicit customer-authored message
     - Recent customer-authored messages
     - Trusted normalized LeadEvidence derived from customer behavior
   ZERO authority:
     - Assistant messages
     - Company prompt / knowledge
     - Lead memory summaries
3. Model explicitness, interpretation confidence, root-cause hypotheses, hypothesis confidence,
   blocking level, and cross-turn objection status separately.
4. "غالي" alone models PRICE_TOO_HIGH with root_cause_hypothesis = UNKNOWN.
   It does NOT guess BUDGET_LIMIT without explicit budget evidence.
5. Direct questions ("بكام؟", "الضمان كام؟") are NOT objections.
   Direct rejections ("مش مهتم خلاص") are REJECTION, NOT objections.
   Post-sale support ("عايز أرجع") is SUPPORT, NOT objections.
6. Assistant answering an objection does NOT mark it resolved. Resolution requires customer-authored evidence.
7. Ethical Response Policy enforces bounded response modes and prohibits dark patterns
   (no fake discounts, fake urgency, fake scarcity, fake social proof, loan pressure, competitor defamation).
8. Tenant isolation across all lookups.
9. Zero additional LLM call by default (deterministic evaluation on customer behavior and evidence).
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from services.sales_state_service import (
    BuyerIntent,
    PrimarySalesState,
    SalesStateSnapshot,
    _fold_arabic,
    _matches_any,
    _strip_punctuation,
)

log = logging.getLogger("adam.objection_intelligence")

MODEL_VERSION = "velor_objection_v1"
POLICY_VERSION = "velor_objection_response_v1"


class ObjectionType(str, Enum):
    NONE = "NONE"
    PRICE_TOO_HIGH = "PRICE_TOO_HIGH"
    BUDGET_CONSTRAINT = "BUDGET_CONSTRAINT"
    VALUE_UNCLEAR = "VALUE_UNCLEAR"
    TRUST_CREDIBILITY = "TRUST_CREDIBILITY"
    PRODUCT_FIT = "PRODUCT_FIT"
    FEATURE_GAP = "FEATURE_GAP"
    QUALITY_DURABILITY = "QUALITY_DURABILITY"
    WARRANTY_RISK = "WARRANTY_RISK"
    RETURN_REFUND_RISK = "RETURN_REFUND_RISK"
    DELIVERY_TIME = "DELIVERY_TIME"
    DELIVERY_COST = "DELIVERY_COST"
    AVAILABILITY = "AVAILABILITY"
    PAYMENT_METHOD = "PAYMENT_METHOD"
    INSTALLMENT_TERMS = "INSTALLMENT_TERMS"
    TIMING_NOT_NOW = "TIMING_NOT_NOW"
    DECISION_AUTHORITY = "DECISION_AUTHORITY"
    INTERNAL_APPROVAL = "INTERNAL_APPROVAL"
    COMPETITOR_COMPARISON = "COMPETITOR_COMPARISON"
    SWITCHING_COST = "SWITCHING_COST"
    COMPLEXITY_EFFORT = "COMPLEXITY_EFFORT"
    NEED_UNCERTAINTY = "NEED_UNCERTAINTY"
    PAST_BAD_EXPERIENCE = "PAST_BAD_EXPERIENCE"
    NEGOTIATION_POSITION = "NEGOTIATION_POSITION"
    OTHER = "OTHER"


class ObjectionExplicitness(str, Enum):
    EXPLICIT = "EXPLICIT"
    IMPLICIT = "IMPLICIT"
    AMBIGUOUS = "AMBIGUOUS"
    ABSENT = "ABSENT"


class RootCauseHypothesis(str, Enum):
    UNKNOWN = "UNKNOWN"
    BUDGET_LIMIT = "BUDGET_LIMIT"
    PERCEIVED_VALUE_GAP = "PERCEIVED_VALUE_GAP"
    TRUST_GAP = "TRUST_GAP"
    FIT_UNCERTAINTY = "FIT_UNCERTAINTY"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    TIMING_CONSTRAINT = "TIMING_CONSTRAINT"
    COMMERCIAL_CONSTRAINT = "COMMERCIAL_CONSTRAINT"
    PAYMENT_FLEXIBILITY_NEED = "PAYMENT_FLEXIBILITY_NEED"
    OPERATIONAL_CONSTRAINT = "OPERATIONAL_CONSTRAINT"
    EXTERNAL_DECISION_DEPENDENCY = "EXTERNAL_DECISION_DEPENDENCY"
    ALTERNATIVE_PREFERENCE = "ALTERNATIVE_PREFERENCE"
    PAST_EXPERIENCE_CONCERN = "PAST_EXPERIENCE_CONCERN"
    NEGOTIATION_POSITIONING = "NEGOTIATION_POSITIONING"


class BlockingLevel(str, Enum):
    NON_BLOCKING = "NON_BLOCKING"
    MAY_BLOCK = "MAY_BLOCK"
    BLOCKING = "BLOCKING"
    UNKNOWN = "UNKNOWN"


class ObjectionStatus(str, Enum):
    NONE = "NONE"
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    CLARIFIED = "CLARIFIED"
    RESOLVED_BY_CUSTOMER = "RESOLVED_BY_CUSTOMER"
    UNKNOWN = "UNKNOWN"


class EthicalResponseMode(str, Enum):
    NO_OBJECTION_RESPONSE = "NO_OBJECTION_RESPONSE"
    ACKNOWLEDGE_CONCERN = "ACKNOWLEDGE_CONCERN"
    CLARIFY_ROOT_CAUSE = "CLARIFY_ROOT_CAUSE"
    ANSWER_WITH_TRUSTED_FACTS = "ANSWER_WITH_TRUSTED_FACTS"
    EXPLAIN_SUPPORTED_VALUE = "EXPLAIN_SUPPORTED_VALUE"
    COMPARE_SUPPORTED_DIFFERENCES = "COMPARE_SUPPORTED_DIFFERENCES"
    ADDRESS_FIT_WITH_SUPPORTED_FACTS = "ADDRESS_FIT_WITH_SUPPORTED_FACTS"
    STATE_TRUSTED_COMMERCIAL_BOUNDARY = "STATE_TRUSTED_COMMERCIAL_BOUNDARY"
    OFFER_TRUSTED_ALTERNATIVE = "OFFER_TRUSTED_ALTERNATIVE"
    RESPECT_TIMING = "RESPECT_TIMING"
    REQUEST_DECISION_CRITERION = "REQUEST_DECISION_CRITERION"
    SUPPORT_TRUST_REPAIR = "SUPPORT_TRUST_REPAIR"
    OFFER_HUMAN_HANDOFF = "OFFER_HUMAN_HANDOFF"
    STOP_SELLING = "STOP_SELLING"


class ObjectionReasonCode(str, Enum):
    EXPLICIT_PRICE_TOO_HIGH = "EXPLICIT_PRICE_TOO_HIGH"
    EXPLICIT_BUDGET_LIMIT = "EXPLICIT_BUDGET_LIMIT"
    PERCEIVED_VALUE_QUESTION = "PERCEIVED_VALUE_QUESTION"
    TRUST_OR_CREDIBILITY_CONCERN = "TRUST_OR_CREDIBILITY_CONCERN"
    WARRANTY_OR_GUARANTEE_CONCERN = "WARRANTY_OR_GUARANTEE_CONCERN"
    DELIVERY_TIMELINE_CONCERN = "DELIVERY_TIMELINE_CONCERN"
    DELIVERY_COST_CONCERN = "DELIVERY_COST_CONCERN"
    INSTALLMENT_OR_TERMS_INQUIRY = "INSTALLMENT_OR_TERMS_INQUIRY"
    DECISION_AUTHORITY_DEPENDENCY = "DECISION_AUTHORITY_DEPENDENCY"
    COMPETITOR_COMPARISON_MENTION = "COMPETITOR_COMPARISON_MENTION"
    TIMING_DEFERRAL_STATEMENT = "TIMING_DEFERRAL_STATEMENT"
    PAST_EXPERIENCE_MENTION = "PAST_EXPERIENCE_MENTION"
    FEATURE_GAP_MENTION = "FEATURE_GAP_MENTION"
    PRODUCT_FIT_CONCERN = "PRODUCT_FIT_CONCERN"
    NEGOTIATION_PRICING_PROBE = "NEGOTIATION_PRICING_PROBE"
    EXPLICIT_REJECTION_SIGNAL = "EXPLICIT_REJECTION_SIGNAL"
    SUPPORT_INTENT_SIGNAL = "SUPPORT_INTENT_SIGNAL"
    DIRECT_QUESTION_NOT_OBJECTION = "DIRECT_QUESTION_NOT_OBJECTION"
    CONTRADICTORY_COMMITMENT_SIGNAL = "CONTRADICTORY_COMMITMENT_SIGNAL"
    CUSTOMER_RESOLVED_SIGNAL = "CUSTOMER_RESOLVED_SIGNAL"
    ASSISTANT_NO_OBJECTION_AUTHORITY = "ASSISTANT_NO_OBJECTION_AUTHORITY"


@dataclass
class ObjectionSnapshot:
    company_id: str
    lead_id: Optional[int]
    conversation_id: Optional[str]
    message_id: Optional[str]
    objection_present: bool
    primary_objection: str
    secondary_objections: List[str] = field(default_factory=list)
    explicitness: str = ObjectionExplicitness.ABSENT.value
    confidence: float = 0.5
    root_cause_hypothesis: str = RootCauseHypothesis.UNKNOWN.value
    root_cause_confidence: float = 0.3
    blocking_level: str = BlockingLevel.UNKNOWN.value
    status: str = ObjectionStatus.NONE.value
    previous_primary_objection: Optional[str] = None
    transition: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_version: str = MODEL_VERSION

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.root_cause_confidence = max(0.0, min(1.0, float(self.root_cause_confidence)))

        valid_types = {t.value for t in ObjectionType}
        if self.primary_objection not in valid_types:
            log.warning("Invalid primary_objection %s, coercing to OTHER", self.primary_objection)
            self.primary_objection = ObjectionType.OTHER.value

        cleaned_sec = []
        for sec in self.secondary_objections:
            if sec in valid_types and sec != self.primary_objection and sec not in cleaned_sec:
                cleaned_sec.append(sec)
        self.secondary_objections = cleaned_sec[:3]

        if self.explicitness not in {e.value for e in ObjectionExplicitness}:
            self.explicitness = ObjectionExplicitness.ABSENT.value

        if self.root_cause_hypothesis not in {r.value for r in RootCauseHypothesis}:
            self.root_cause_hypothesis = RootCauseHypothesis.UNKNOWN.value

        if self.blocking_level not in {b.value for b in BlockingLevel}:
            self.blocking_level = BlockingLevel.UNKNOWN.value

        if self.status not in {s.value for s in ObjectionStatus}:
            self.status = ObjectionStatus.NONE.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ObjectionSnapshot":
        return cls(
            company_id=data.get("company_id", ""),
            lead_id=data.get("lead_id"),
            conversation_id=data.get("conversation_id"),
            message_id=data.get("message_id"),
            objection_present=data.get("objection_present", False),
            primary_objection=data.get("primary_objection", ObjectionType.NONE.value),
            secondary_objections=data.get("secondary_objections", []),
            explicitness=data.get("explicitness", ObjectionExplicitness.ABSENT.value),
            confidence=data.get("confidence", 0.5),
            root_cause_hypothesis=data.get("root_cause_hypothesis", RootCauseHypothesis.UNKNOWN.value),
            root_cause_confidence=data.get("root_cause_confidence", 0.3),
            blocking_level=data.get("blocking_level", BlockingLevel.UNKNOWN.value),
            status=data.get("status", ObjectionStatus.NONE.value),
            previous_primary_objection=data.get("previous_primary_objection"),
            transition=data.get("transition"),
            evidence_refs=data.get("evidence_refs", []),
            reason_codes=data.get("reason_codes", []),
            observed_at=data.get("observed_at", datetime.now(timezone.utc).isoformat()),
            model_version=data.get("model_version", MODEL_VERSION),
        )


@dataclass
class EthicalObjectionResponsePolicy:
    company_id: str
    lead_id: Optional[int]
    objection_snapshot_ref: Optional[str]
    primary_response_mode: str
    secondary_modes: List[str] = field(default_factory=list)
    response_steps: List[str] = field(default_factory=list)
    question_policy: str = "ONE_OPTIONAL_QUESTION"
    cta_policy: str = "SOFT"
    pressure_ceiling: str = "LOW"
    trusted_fact_requirements: List[str] = field(default_factory=list)
    prohibited_tactics: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    policy_version: str = POLICY_VERSION

    def __post_init__(self):
        valid_modes = {m.value for m in EthicalResponseMode}
        if self.primary_response_mode not in valid_modes:
            self.primary_response_mode = EthicalResponseMode.NO_OBJECTION_RESPONSE.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Pattern collections for Arabic, English, and Mixed language detection

_QUESTION_PATTERNS = [
    r"بكام",
    r"كام\s+سعر",
    r"كم\s+سعر",
    r"كام\_الضمان",
    r"الضمان\s+كام",
    r"مدة\s+الضمان",
    r"التوصيل\s+بياخد\s+كام",
    r"بياخد\s+وقت\s+أد إيه",
    r"بياخد\s+وقت\s+قد ايه",
    r"طريقة\s+الدفع\s+إيه",
    r"فيه\s+تقسيط\؟",
    r"فيه\s+شحن\؟",
    r"فيه\s+لون\s+أسود\؟",
    r"قارنلي\s+بينهم",
    r"how\s+much",
    r"what\s+is\s+the\s+price",
    r"how\s+long\s+is\s+the\s+warranty",
    r"how\s+long\s+does\s+delivery\s+take",
    r"do\s+you\s+have\s+installments\?",
]

_REJECTION_PATTERNS = [
    r"مش\s+مهتم",
    r"مش\s+عايز\s+أكمل",
    r"مش\s+عايز\s+اكمل",
    r"الغي\s+الطلب",
    r"ألف\s+شكرا\s+مش\s+محتاج",
    r"مش\  عايز",
    r"لا\s+شكرا",
    r"not\s+interested",
    r"cancel\s+my\s+order",
    r"don't\s+want\s+it",
    r"stop\s+messaging",
]

_SUPPORT_PATTERNS = [
    r"الطلب\s+وصل\s+ناقص",
    r"عايز\s+أرجع\s+المنتج",
    r"عايز\s+ارجع",
    r"فين\s+الشحنة",
    r"الشحنة\s+تأخرت",
    r"المنتج\s+فيه\s+مشكلة",
    r"my\s+order\s+is\s+missing",
    r"want\s+to\s+return",
    r"where\s+is\s+my\s+shipment",
]

_BUDGET_EXPLICIT_PATTERNS = [
    r"معايا\s*(\d+|[٠-٩]+)\s*(بس|جنيه|جنية|فقط)?",
    r"ميزانيتي\s*(\d+|[٠-٩]+)",
    r"أقصى\s+حاجة\s*(\d+|[٠-٩]+)",
    r"my\s+budget\s+is\s*(\d+)",
    r"i\s+only\s+have\s*(a\s+)?(\d+)",
    r"budget\s+.*?\s*(\d+)",
    r"(\d+)\s*budget",
]

_PRICE_HIGH_PATTERNS = [
    r"\bغالي\b",
    r"\bغاليه\b",
    r"\bغالي\s+أوي\b",
    r"\bغالي\s+اوي\b",
    r"\bالسعر\s+عالي\b",
    r"\bالسعر\s+مرتفع\b",
    r"\bغالي\s+جدا\b",
    r"too\s+expensive",
    r"price\s+is\s+high",
    r"overpriced",
    r"غالي\s+but",
    r"غالي\s+بس",
]

_VALUE_UNCLEAR_PATTERNS = [
    r"مش\s+شايف\s+إنه\s+يستاهل",
    r"مش\s+شايف\s+انه\s+يستاهل",
    r"ليه\s+أدفع",
    r"ليه\s+ادفع",
    r"مش\s+مستاهل\s+السعر",
    r"don't\s+think\s+it's\s+worth",
    r"not\s+worth\s+the\s+price",
    r"why\s+should\s+i\s+pay",
]

_NEGOTIATION_PATTERNS = [
    r"آخر\s+سعر",
    r"اخر\s+سعر",
    r"مفيش\s+كلام\s+في\s+السعر",
    r"مفيش\s+خصم",
    r"أعملي\s+خصم",
    r"لو\s+خدت\s*\d+\s*تعمل\s+خصم",
    r"best\s+price",
    r"what's\s+your\s+best\s+price",
    r"can\s+you\s+discount",
]

_COMPETITOR_PATTERNS = [
    r"المنافس\s+أرخص",
    r"المنافس\s+ارخص",
    r"عند\s+الشركة\s+التانية\s+أرخص",
    r"شفت\s+أرخص\s+بره",
    r"competitor\s+is\s+cheaper",
    r"cheaper\s+somewhere\s+else",
    r"competitor\s+أرخص",
]

_TRUST_PATTERNS = [
    r"مش\s+واثق\s+في\s+الشركة",
    r"مش\s+واثق",
    r"خايف\s+اتنصب",
    r"خايف\s+يتنصب\s+علي",
    r"don't\s+trust",
    r"not\s+sure\s+i\s+trust",
]

_WARRANTY_PATTERNS = [
    r"الضمان\s+مش\s+مطمني",
    r"الضمان\s+سنة\s+بس\؟\s*ده\s+قليل",
    r"الضمان\s+قليل",
    r"خايف\s+من\s+الضمان",
    r"worried\s+about\s+the\s+warranty",
    r"warranty\s+مش\s+مطمني",
    r"warranty\s+is\s+too\s+short",
]

_PAST_EXPERIENCE_PATTERNS = [
    r"جربتكم\s+قبل\s+كده\s+وكانت\s+التجربة\s+سيئة",
    r"جربتكم\s+وكانت\s+وحشة",
    r"تجربتي\s+القديمة\s+معاكم\s+سيئة",
    r"had\s+a\s+bad\s+experience\s+before",
]

_QUALITY_PATTERNS = [
    r"خايف\s+يبوظ\s+سرعة",
    r"خايف\s+يبوظ",
    r"الجودة\s+مش\s+مضمونة",
    r"worried\s+about\s+quality",
]

_DELIVERY_TIME_PATTERNS = [
    r"التوصيل\s+متأخر",
    r"أسبوع\s+توصيل\s+كتير",
    r"اسبوع\s+توصيل\s+كتير",
    r"التوصيل\s+.*?\s*كتير",
    r"التوصيل\s+بياخد\s+وقت\s+كتير",
    r"delivery\s+takes\s+too\s+long",
]

_DELIVERY_COST_PATTERNS = [
    r"الشحن\s+غالي",
    r"مصاريف\s+الشحن\s+عالية",
    r"shipping\s+is\s+expensive",
]

_INSTALLMENT_PATTERNS = [
    r"ينفع\s+تقسيط\؟",
    r"ينفع\s+على\s*\d+\s*شهور",
    r"تقسيط\s+على",
    r"can\s+i\s+pay\s+in\s+installments",
    r"installments\s+متاحة",
    r"عايز\s+installments",
]

_TIMING_PATTERNS = [
    r"مش\s+دلوقتي",
    r"يمكن\s+الشهر\s+الجاي",
    r"استنى\s+المرتب",
    r"مستني\s+المرتب",
    r"هفكر",
    r"سيبني\s+أفكر",
    r"not\s+right\s+now",
    r"maybe\s+next\s+month",
    r"waiting\s+for\s+salary",
]

_DECISION_AUTHORITY_PATTERNS = [
    r"لازم\s+أسأل\s+المدير",
    r"لازم\s+اسأل\s+المدير",
    r"القرار\s+مش\s+بتاعي",
    r"هراجع\s+شريكي",
    r"لازم\s+أستشير",
    r"need\s+to\s+ask\s+my\s+manager",
    r"decision\s+is\s+not\s+mine",
    r"لازم\s+ask\s+my\s+manager",
]

_PRODUCT_FIT_PATTERNS = [
    r"مش\s+متأكد\s+يناسبني",
    r"مش\s+متأكد\s+يناسب\s+ضهري",
    r"not\s+sure\s+it\s+fits\s+my\s+needs",
    r"مش\s+sure\s+يناسبني",
]

_FEATURE_GAP_PATTERNS = [
    r"محتاج\s+.*ومش\s+موجود",
    r"ناقصة\s+ميزة",
    r"it\s+doesn't\s+have\s+the\s+feature",
    r"missing\s+feature",
]

_ACTIVE_COMMITMENT_PATTERNS = [
    r"ابعتلي\s+رقم\s+الدفع",
    r"ابعت\s+الدفع",
    r"عايز\s+أطلب",
    r"جاهز\s+للشراء",
    r"send\s+me\s+the\s+payment\s+link",
    r"send\s+payment\s+link",
]


def evaluate_objection_intelligence(
    session: Optional[Session],
    company_id: str,
    lead_id: Optional[int],
    latest_user_message: str,
    sales_snapshot: Optional[SalesStateSnapshot] = None,
    previous_objection_snapshot: Optional[ObjectionSnapshot] = None,
) -> ObjectionSnapshot:
    """
    Evaluates customer objection intelligence strictly from customer behavior.
    """
    text = (latest_user_message or "").strip()
    folded_text = _fold_arabic(text)
    lower_text = text.lower()

    reason_codes: List[str] = []
    evidence_refs: List[str] = []
    primary_objection = ObjectionType.NONE.value
    secondary_objections: List[str] = []
    explicitness = ObjectionExplicitness.ABSENT.value
    confidence = 0.5
    root_cause = RootCauseHypothesis.UNKNOWN.value
    root_cause_conf = 0.3
    blocking_level = BlockingLevel.NON_BLOCKING.value if text else BlockingLevel.UNKNOWN.value
    status = ObjectionStatus.NONE.value
    objection_present = False

    # Check boundaries first (Questions, Rejections, Support)
    is_direct_q = any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _QUESTION_PATTERNS)
    # Exclude questions that explicitly carry a strong complaint qualification e.g., "الضمان سنة بس؟ ده قليل"
    is_qualified_complaint = any(token in folded_text for token in ["ده قليل", "قليل جدا", "short", "too short"])

    if is_direct_q and not is_qualified_complaint:
        reason_codes.append(ObjectionReasonCode.DIRECT_QUESTION_NOT_OBJECTION.value)
        return ObjectionSnapshot(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id if sales_snapshot else None,
            message_id=None,
            objection_present=False,
            primary_objection=ObjectionType.NONE.value,
            secondary_objections=[],
            explicitness=ObjectionExplicitness.ABSENT.value,
            confidence=0.9,
            root_cause_hypothesis=RootCauseHypothesis.UNKNOWN.value,
            root_cause_confidence=0.1,
            blocking_level=BlockingLevel.NON_BLOCKING.value,
            status=ObjectionStatus.NONE.value,
            previous_primary_objection=previous_objection_snapshot.primary_objection if previous_objection_snapshot else None,
            evidence_refs=["customer_direct_question"],
            reason_codes=reason_codes,
            model_version=MODEL_VERSION,
        )

    is_rejection = any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _REJECTION_PATTERNS)
    if is_rejection:
        reason_codes.append(ObjectionReasonCode.EXPLICIT_REJECTION_SIGNAL.value)
        return ObjectionSnapshot(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id if sales_snapshot else None,
            message_id=None,
            objection_present=False,
            primary_objection=ObjectionType.NONE.value,
            secondary_objections=[],
            explicitness=ObjectionExplicitness.ABSENT.value,
            confidence=0.95,
            root_cause_hypothesis=RootCauseHypothesis.UNKNOWN.value,
            root_cause_confidence=0.1,
            blocking_level=BlockingLevel.BLOCKING.value,
            status=ObjectionStatus.NONE.value,
            previous_primary_objection=previous_objection_snapshot.primary_objection if previous_objection_snapshot else None,
            evidence_refs=["customer_explicit_rejection"],
            reason_codes=reason_codes,
            model_version=MODEL_VERSION,
        )

    is_support = any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _SUPPORT_PATTERNS)
    if is_support:
        reason_codes.append(ObjectionReasonCode.SUPPORT_INTENT_SIGNAL.value)
        return ObjectionSnapshot(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id if sales_snapshot else None,
            message_id=None,
            objection_present=False,
            primary_objection=ObjectionType.NONE.value,
            secondary_objections=[],
            explicitness=ObjectionExplicitness.ABSENT.value,
            confidence=0.95,
            root_cause_hypothesis=RootCauseHypothesis.UNKNOWN.value,
            root_cause_confidence=0.1,
            blocking_level=BlockingLevel.NON_BLOCKING.value,
            status=ObjectionStatus.NONE.value,
            previous_primary_objection=previous_objection_snapshot.primary_objection if previous_objection_snapshot else None,
            evidence_refs=["customer_post_sale_support"],
            reason_codes=reason_codes,
            model_version=MODEL_VERSION,
        )

    # Check for resolution by customer in current message
    is_resolved_signal = any(token in folded_text for token in ["تمام كده فهمت", "فهمت خلاص", "understood now", "clear now"])
    has_active_commitment = any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _ACTIVE_COMMITMENT_PATTERNS)

    if is_resolved_signal:
        reason_codes.append(ObjectionReasonCode.CUSTOMER_RESOLVED_SIGNAL.value)
        status = ObjectionStatus.RESOLVED_BY_CUSTOMER.value
        blocking_level = BlockingLevel.NON_BLOCKING.value

    # Primary & Secondary Objections Detection
    detected_objections: List[Tuple[str, str, float, str, float]] = []

    # 1. Budget Constraint (explicit amount)
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _BUDGET_EXPLICIT_PATTERNS):
        detected_objections.append((
            ObjectionType.BUDGET_CONSTRAINT.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.95,
            RootCauseHypothesis.BUDGET_LIMIT.value,
            0.9,
        ))
        reason_codes.append(ObjectionReasonCode.EXPLICIT_BUDGET_LIMIT.value)
        evidence_refs.append("explicit_budget_amount")

    # 2. Value Unclear
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _VALUE_UNCLEAR_PATTERNS):
        detected_objections.append((
            ObjectionType.VALUE_UNCLEAR.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.90,
            RootCauseHypothesis.PERCEIVED_VALUE_GAP.value,
            0.85,
        ))
        reason_codes.append(ObjectionReasonCode.PERCEIVED_VALUE_QUESTION.value)
        evidence_refs.append("value_doubt_statement")

    # 3. Price Too High ("غالي" alone or general price high)
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _PRICE_HIGH_PATTERNS):
        # Only add PRICE_TOO_HIGH if BUDGET_CONSTRAINT and VALUE_UNCLEAR are not already present, or add as secondary
        detected_objections.append((
            ObjectionType.PRICE_TOO_HIGH.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.90,
            RootCauseHypothesis.UNKNOWN.value,  # Mandatory: DO NOT guess BUDGET_LIMIT
            0.30,
        ))
        reason_codes.append(ObjectionReasonCode.EXPLICIT_PRICE_TOO_HIGH.value)
        evidence_refs.append("price_too_high_statement")

    # 4. Negotiation Position
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _NEGOTIATION_PATTERNS):
        detected_objections.append((
            ObjectionType.NEGOTIATION_POSITION.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.NEGOTIATION_POSITIONING.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.NEGOTIATION_PRICING_PROBE.value)
        evidence_refs.append("negotiation_price_probe")

    # 5. Competitor Comparison
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _COMPETITOR_PATTERNS):
        detected_objections.append((
            ObjectionType.COMPETITOR_COMPARISON.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.90,
            RootCauseHypothesis.ALTERNATIVE_PREFERENCE.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.COMPETITOR_COMPARISON_MENTION.value)
        evidence_refs.append("competitor_comparison_statement")

    # 6. Trust Credibility
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _TRUST_PATTERNS):
        detected_objections.append((
            ObjectionType.TRUST_CREDIBILITY.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.90,
            RootCauseHypothesis.TRUST_GAP.value,
            0.85,
        ))
        reason_codes.append(ObjectionReasonCode.TRUST_OR_CREDIBILITY_CONCERN.value)
        evidence_refs.append("trust_credibility_statement")

    # 7. Warranty Risk
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _WARRANTY_PATTERNS):
        detected_objections.append((
            ObjectionType.WARRANTY_RISK.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.90,
            RootCauseHypothesis.MISSING_INFORMATION.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.WARRANTY_OR_GUARANTEE_CONCERN.value)
        evidence_refs.append("warranty_risk_statement")

    # 8. Past Bad Experience
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _PAST_EXPERIENCE_PATTERNS):
        detected_objections.append((
            ObjectionType.PAST_BAD_EXPERIENCE.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.95,
            RootCauseHypothesis.PAST_EXPERIENCE_CONCERN.value,
            0.90,
        ))
        reason_codes.append(ObjectionReasonCode.PAST_EXPERIENCE_MENTION.value)
        evidence_refs.append("past_experience_statement")

    # 9. Quality / Durability
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _QUALITY_PATTERNS):
        detected_objections.append((
            ObjectionType.QUALITY_DURABILITY.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.PERCEIVED_VALUE_GAP.value,
            0.75,
        ))
        evidence_refs.append("quality_durability_statement")

    # 10. Delivery Time
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _DELIVERY_TIME_PATTERNS):
        detected_objections.append((
            ObjectionType.DELIVERY_TIME.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.OPERATIONAL_CONSTRAINT.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.DELIVERY_TIMELINE_CONCERN.value)
        evidence_refs.append("delivery_time_statement")

    # 11. Delivery Cost
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _DELIVERY_COST_PATTERNS):
        detected_objections.append((
            ObjectionType.DELIVERY_COST.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.COMMERCIAL_CONSTRAINT.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.DELIVERY_COST_CONCERN.value)
        evidence_refs.append("delivery_cost_statement")

    # 12. Installment Terms
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _INSTALLMENT_PATTERNS):
        detected_objections.append((
            ObjectionType.INSTALLMENT_TERMS.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.PAYMENT_FLEXIBILITY_NEED.value,
            0.85,
        ))
        reason_codes.append(ObjectionReasonCode.INSTALLMENT_OR_TERMS_INQUIRY.value)
        evidence_refs.append("installment_terms_statement")

    # 13. Timing / Not Now
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _TIMING_PATTERNS):
        detected_objections.append((
            ObjectionType.TIMING_NOT_NOW.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.TIMING_CONSTRAINT.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.TIMING_DEFERRAL_STATEMENT.value)
        evidence_refs.append("timing_deferral_statement")

    # 14. Decision Authority
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _DECISION_AUTHORITY_PATTERNS):
        detected_objections.append((
            ObjectionType.DECISION_AUTHORITY.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.90,
            RootCauseHypothesis.EXTERNAL_DECISION_DEPENDENCY.value,
            0.85,
        ))
        reason_codes.append(ObjectionReasonCode.DECISION_AUTHORITY_DEPENDENCY.value)
        evidence_refs.append("decision_authority_statement")

    # 15. Product Fit
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _PRODUCT_FIT_PATTERNS):
        detected_objections.append((
            ObjectionType.PRODUCT_FIT.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.FIT_UNCERTAINTY.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.PRODUCT_FIT_CONCERN.value)
        evidence_refs.append("product_fit_statement")

    # 16. Feature Gap
    if any(re.search(pat, folded_text, re.I) or re.search(pat, lower_text, re.I) for pat in _FEATURE_GAP_PATTERNS):
        detected_objections.append((
            ObjectionType.FEATURE_GAP.value,
            ObjectionExplicitness.EXPLICIT.value,
            0.85,
            RootCauseHypothesis.FIT_UNCERTAINTY.value,
            0.80,
        ))
        reason_codes.append(ObjectionReasonCode.FEATURE_GAP_MENTION.value)
        evidence_refs.append("feature_gap_statement")

    if detected_objections:
        objection_present = True
        # Sort so specific price objections (BUDGET_CONSTRAINT, VALUE_UNCLEAR) take precedence over general PRICE_TOO_HIGH if both detected
        priority_order = {
            ObjectionType.BUDGET_CONSTRAINT.value: 10,
            ObjectionType.VALUE_UNCLEAR.value: 9,
            ObjectionType.TRUST_CREDIBILITY.value: 9,
            ObjectionType.WARRANTY_RISK.value: 9,
            ObjectionType.PAST_BAD_EXPERIENCE.value: 9,
            ObjectionType.COMPETITOR_COMPARISON.value: 8,
            ObjectionType.DECISION_AUTHORITY.value: 8,
            ObjectionType.PRICE_TOO_HIGH.value: 5,
            ObjectionType.TIMING_NOT_NOW.value: 5,
            ObjectionType.INSTALLMENT_TERMS.value: 5,
        }
        detected_objections.sort(key=lambda x: priority_order.get(x[0], 4), reverse=True)

        primary_objection, explicitness, confidence, root_cause, root_cause_conf = detected_objections[0]

        for sec in detected_objections[1:]:
            if sec[0] != primary_objection and sec[0] not in secondary_objections:
                secondary_objections.append(sec[0])

        if status != ObjectionStatus.RESOLVED_BY_CUSTOMER.value:
            status = ObjectionStatus.NEW.value if not previous_objection_snapshot or previous_objection_snapshot.primary_objection != primary_objection else ObjectionStatus.ACTIVE.value

        # Blocking level assessment: check if active purchase commitment is present alongside objection
        if has_active_commitment:
            blocking_level = BlockingLevel.NON_BLOCKING.value
            reason_codes.append(ObjectionReasonCode.CONTRADICTORY_COMMITMENT_SIGNAL.value)
        else:
            if primary_objection in {ObjectionType.BUDGET_CONSTRAINT.value, ObjectionType.TRUST_CREDIBILITY.value, ObjectionType.PAST_BAD_EXPERIENCE.value}:
                blocking_level = BlockingLevel.BLOCKING.value
            else:
                blocking_level = BlockingLevel.MAY_BLOCK.value
    else:
        # Cross-turn state persistence: if previous objection active and customer message is ambiguous/short ack, preserve or transition
        if previous_objection_snapshot and previous_objection_snapshot.objection_present and previous_objection_snapshot.status in {ObjectionStatus.NEW.value, ObjectionStatus.ACTIVE.value}:
            # If customer message is simple "تمام" or "شكرا" without resolution signal, preserve active status softly
            if folded_text in {"تمام", "شكرا", "اوكي", "ماشي", "ok", "thanks"}:
                objection_present = True
                primary_objection = previous_objection_snapshot.primary_objection
                secondary_objections = previous_objection_snapshot.secondary_objections
                explicitness = ObjectionExplicitness.IMPLICIT.value
                confidence = 0.6
                root_cause = previous_objection_snapshot.root_cause_hypothesis
                root_cause_conf = previous_objection_snapshot.root_cause_confidence
                blocking_level = BlockingLevel.MAY_BLOCK.value
                status = ObjectionStatus.ACTIVE.value
                evidence_refs.append("preserved_cross_turn_objection")

    transition = None
    if previous_objection_snapshot and previous_objection_snapshot.primary_objection != primary_objection:
        transition = f"{previous_objection_snapshot.primary_objection}->{primary_objection}"

    return ObjectionSnapshot(
        company_id=company_id,
        lead_id=lead_id,
        conversation_id=sales_snapshot.conversation_id if sales_snapshot else None,
        message_id=None,
        objection_present=objection_present,
        primary_objection=primary_objection,
        secondary_objections=secondary_objections,
        explicitness=explicitness,
        confidence=confidence,
        root_cause_hypothesis=root_cause,
        root_cause_confidence=root_cause_conf,
        blocking_level=blocking_level,
        status=status,
        previous_primary_objection=previous_objection_snapshot.primary_objection if previous_objection_snapshot else None,
        transition=transition,
        evidence_refs=evidence_refs,
        reason_codes=list(dict.fromkeys(reason_codes)),
        model_version=MODEL_VERSION,
    )


def evaluate_ethical_objection_response_policy(
    company_id: str,
    lead_id: Optional[int],
    objection_snapshot: ObjectionSnapshot,
    action_decision: Optional[Any] = None,
    sales_snapshot: Optional[SalesStateSnapshot] = None,
) -> EthicalObjectionResponsePolicy:
    """
    Evaluates ethical response policy for the active objection snapshot.
    Ensures zero dark patterns and strict compliance with ethical sales strategy.
    """
    if not objection_snapshot.objection_present or objection_snapshot.status == ObjectionStatus.RESOLVED_BY_CUSTOMER.value:
        return EthicalObjectionResponsePolicy(
            company_id=company_id,
            lead_id=lead_id,
            objection_snapshot_ref=objection_snapshot.primary_objection,
            primary_response_mode=EthicalResponseMode.NO_OBJECTION_RESPONSE.value,
            secondary_modes=[],
            response_steps=[],
            question_policy="NO_QUESTION",
            cta_policy="NONE",
            pressure_ceiling="NONE",
            trusted_fact_requirements=[],
            prohibited_tactics=[],
            reason_codes=["NO_ACTIVE_OBJECTION"],
            policy_version=POLICY_VERSION,
        )

    p_obj = objection_snapshot.primary_objection
    root_cause = objection_snapshot.root_cause_hypothesis

    response_mode = EthicalResponseMode.ACKNOWLEDGE_CONCERN.value
    steps = ["ACKNOWLEDGE"]
    prohibited: List[str] = [
        "INVENT_DISCOUNT",
        "CREATE_URGENCY",
        "CREATE_SCARCITY",
        "FABRICATE_REVIEWS",
        "DEFAME_COMPETITOR",
        "SHAME_CUSTOMER",
    ]
    fact_reqs: List[str] = []
    question_policy = "ONE_OPTIONAL_QUESTION"
    cta_policy = "SOFT"
    pressure_ceiling = "LOW"
    reason_codes: List[str] = [f"POLICY_FOR_{p_obj}"]

    if p_obj == ObjectionType.PRICE_TOO_HIGH.value:
        if root_cause == RootCauseHypothesis.UNKNOWN.value:
            response_mode = EthicalResponseMode.CLARIFY_ROOT_CAUSE.value
            steps = ["ACKNOWLEDGE", "ASK_ONE_CLARIFIER"]
            question_policy = "ONE_REQUIRED_CLARIFIER"
            cta_policy = "NONE"
            prohibited.extend(["ASSUME_BUDGET_LIMIT", "PUSH_FOR_PAYMENT"])
        else:
            response_mode = EthicalResponseMode.EXPLAIN_SUPPORTED_VALUE.value
            steps = ["ACKNOWLEDGE", "STATE_SUPPORTED_FACTS", "OFFER_OPTIONAL_CONTINUATION"]
            fact_reqs.append("catalog_verified_price")

    elif p_obj == ObjectionType.BUDGET_CONSTRAINT.value:
        response_mode = EthicalResponseMode.OFFER_TRUSTED_ALTERNATIVE.value
        steps = ["ACKNOWLEDGE", "COMPARE_RELEVANT_OPTIONS"]
        question_policy = "ONE_DECISION_QUESTION"
        prohibited.extend(["RECOMMEND_LOANS", "INVENT_FINANCING", "PUSH_FOR_PAYMENT"])
        fact_reqs.append("catalog_alternative_products")

    elif p_obj == ObjectionType.VALUE_UNCLEAR.value:
        response_mode = EthicalResponseMode.EXPLAIN_SUPPORTED_VALUE.value
        steps = ["ACKNOWLEDGE", "STATE_SUPPORTED_FACTS"]
        prohibited.extend(["FAKE_ROI", "FAKE_QUALITY_CLAIMS", "FAKE_SOCIAL_PROOF"])
        fact_reqs.append("product_verified_features")

    elif p_obj == ObjectionType.TRUST_CREDIBILITY.value:
        response_mode = EthicalResponseMode.SUPPORT_TRUST_REPAIR.value
        steps = ["ACKNOWLEDGE", "STATE_SUPPORTED_FACTS", "OFFER_HUMAN_HANDOFF"]
        prohibited.extend(["FABRICATE_TESTIMONIALS", "FAKE_CUSTOMER_COUNTS"])
        fact_reqs.append("company_verified_credentials")

    elif p_obj == ObjectionType.WARRANTY_RISK.value:
        response_mode = EthicalResponseMode.ANSWER_WITH_TRUSTED_FACTS.value
        steps = ["ACKNOWLEDGE", "STATE_SUPPORTED_FACTS"]
        prohibited.extend(["INVENT_WARRANTY_TERMS"])
        fact_reqs.append("trusted_warranty_policy")

    elif p_obj == ObjectionType.COMPETITOR_COMPARISON.value:
        response_mode = EthicalResponseMode.COMPARE_SUPPORTED_DIFFERENCES.value
        steps = ["ACKNOWLEDGE", "COMPARE_RELEVANT_OPTIONS"]
        prohibited.extend(["DEFAME_COMPETITOR", "INVENT_COMPETITOR_FACTS"])
        fact_reqs.append("trusted_competitor_comparison_policy")

    elif p_obj == ObjectionType.TIMING_NOT_NOW.value:
        response_mode = EthicalResponseMode.RESPECT_TIMING.value
        steps = ["ACKNOWLEDGE", "OFFER_OPTIONAL_CONTINUATION"]
        question_policy = "NO_QUESTION"
        cta_policy = "NONE"
        pressure_ceiling = "NONE"
        prohibited.extend(["FAKE_DEADLINE", "FAKE_URGENCY", "GUILT_TRIP"])

    elif p_obj == ObjectionType.DECISION_AUTHORITY.value:
        response_mode = EthicalResponseMode.STATE_TRUSTED_COMMERCIAL_BOUNDARY.value
        steps = ["ACKNOWLEDGE", "OFFER_OPTIONAL_CONTINUATION"]
        prohibited.extend(["PRESSURE_BYPASSING_MANAGER"])

    elif p_obj == ObjectionType.PAST_BAD_EXPERIENCE.value:
        response_mode = EthicalResponseMode.SUPPORT_TRUST_REPAIR.value
        steps = ["ACKNOWLEDGE", "OFFER_HUMAN_HANDOFF"]
        prohibited.extend(["DENY_CUSTOMER_EXPERIENCE", "BLAME_CUSTOMER"])

    elif p_obj == ObjectionType.NEGOTIATION_POSITION.value:
        response_mode = EthicalResponseMode.STATE_TRUSTED_COMMERCIAL_BOUNDARY.value
        steps = ["ACKNOWLEDGE", "STATE_SUPPORTED_FACTS"]
        prohibited.extend(["INVENT_UNAUTHORIZED_DISCOUNT"])
        fact_reqs.append("approved_commercial_terms")

    return EthicalObjectionResponsePolicy(
        company_id=company_id,
        lead_id=lead_id,
        objection_snapshot_ref=p_obj,
        primary_response_mode=response_mode,
        secondary_modes=[],
        response_steps=steps,
        question_policy=question_policy,
        cta_policy=cta_policy,
        pressure_ceiling=pressure_ceiling,
        trusted_fact_requirements=fact_reqs,
        prohibited_tactics=list(dict.fromkeys(prohibited)),
        reason_codes=reason_codes,
        policy_version=POLICY_VERSION,
    )
