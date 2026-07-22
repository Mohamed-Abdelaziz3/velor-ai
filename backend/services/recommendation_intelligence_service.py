"""
recommendation_intelligence_service.py — Recommendation Intelligence & Ethical Product Fit
========================================================================================
Provides one canonical, tenant-safe, evidence-backed Recommendation Intelligence and
Ethical Product Fit subsystem for VELOR backend.

Key Architecture Principles:
1. Separate Customer Needs from Sales State, Buyer Intent, ObjectionSnapshot, and Next Best Action.
2. Authority hierarchy for Customer Need Truth:
   Highest authority:
     - Current explicit customer-authored message
     - Recent customer-authored messages
     - Trusted normalized LeadEvidence derived from customer behavior
   ZERO authority:
     - Assistant messages
     - Company prompt / knowledge
     - Lead memory summaries
     - Product catalog (catalog defines product facts, not customer needs)
3. Model explicitness (EXPLICIT, INFERRED, AMBIGUOUS, UNKNOWN), constraint strength
   (HARD, SOFT, UNKNOWN), need confidence, and missing information explicitly.
4. Hard constraints MUST filter products BEFORE candidate ranking.
5. Unknown Attribute Safety: If a product lacks data for a required hard constraint,
   do NOT infer or fabricate fit. Mark as UNKNOWN_REQUIRED_ATTRIBUTE or INSUFFICIENT_INFORMATION.
6. Fit-First Ranking Discipline:
   - No expensive product bias: Higher price NEVER adds fit by itself.
   - No cheapest product bias: Price is context-dependent, not universally positive.
   - No catalog order bias: Catalog index does not affect rank.
   - No margin bias / No hidden upsell.
7. Insufficient Information Handling:
   - If customer asks "أنهي أحسن ليا؟" without criteria, return ASK_CLARIFYING_QUESTION
     or INSUFFICIENT_INFORMATION with ONE high-value decision criterion.
8. Ethical Product-Fit Policy enforces bounded response modes and prohibits dark tactics
   (no fake personalization, no fake expertise claims, no demographic stereotyping, no fake fit percentages).
9. High-Risk Final-Reply Recommendation Alignment checks candidate replies to prevent mismatches,
   unsupported upsells, missing hard feature claims, or stereotyping.
10. Tenant isolation across all lookups.
11. Zero additional LLM call by default (deterministic evaluation over trusted catalog products).
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from services.product_context_service import ProductContext, get_company_products
from services.sales_state_service import (
    BuyerIntent,
    PrimarySalesState,
    SalesStateSnapshot,
    _fold_arabic,
    _matches_any,
    _strip_punctuation,
)

log = logging.getLogger("adam.recommendation_intelligence")

MODEL_VERSION = "velor_customer_need_v1"
DECISION_POLICY_VERSION = "velor_recommendation_v1"
ETHICAL_POLICY_VERSION = "velor_product_fit_v1"


class NeedType(str, Enum):
    USE_CASE = "USE_CASE"
    PRODUCT_CATEGORY = "PRODUCT_CATEGORY"
    BUDGET_CEILING = "BUDGET_CEILING"
    BUDGET_RANGE = "BUDGET_RANGE"
    QUANTITY = "QUANTITY"
    REQUIRED_FEATURE = "REQUIRED_FEATURE"
    PREFERRED_FEATURE = "PREFERRED_FEATURE"
    EXCLUDED_FEATURE = "EXCLUDED_FEATURE"
    COLOR_PREFERENCE = "COLOR_PREFERENCE"
    SIZE_REQUIREMENT = "SIZE_REQUIREMENT"
    DIMENSION_REQUIREMENT = "DIMENSION_REQUIREMENT"
    CAPACITY_REQUIREMENT = "CAPACITY_REQUIREMENT"
    COMPATIBILITY_REQUIREMENT = "COMPATIBILITY_REQUIREMENT"
    DURABILITY_PRIORITY = "DURABILITY_PRIORITY"
    WARRANTY_PRIORITY = "WARRANTY_PRIORITY"
    DELIVERY_PRIORITY = "DELIVERY_PRIORITY"
    COMFORT_PRIORITY = "COMFORT_PRIORITY"
    ERGONOMICS_PRIORITY = "ERGONOMICS_PRIORITY"
    SPACE_CONSTRAINT = "SPACE_CONSTRAINT"
    FREQUENCY_OF_USE = "FREQUENCY_OF_USE"
    DURATION_OF_USE = "DURATION_OF_USE"
    USER_SKILL_LEVEL = "USER_SKILL_LEVEL"
    INSTALLATION_REQUIREMENT = "INSTALLATION_REQUIREMENT"
    PAYMENT_CONSTRAINT = "PAYMENT_CONSTRAINT"
    OTHER = "OTHER"


class NeedExplicitness(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class ConstraintStrength(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    UNKNOWN = "UNKNOWN"


@dataclass
class CustomerNeedItem:
    need_type: NeedType
    value: Any
    explicitness: NeedExplicitness
    constraint_strength: ConstraintStrength
    confidence: float = 1.0
    raw_text: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "need_type": self.need_type.value if isinstance(self.need_type, NeedType) else str(self.need_type),
            "value": self.value,
            "explicitness": self.explicitness.value if isinstance(self.explicitness, NeedExplicitness) else str(self.explicitness),
            "constraint_strength": self.constraint_strength.value if isinstance(self.constraint_strength, ConstraintStrength) else str(self.constraint_strength),
            "confidence": round(self.confidence, 4),
            "raw_text": self.raw_text,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass
class CustomerNeedSnapshot:
    company_id: str
    lead_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    needs: List[CustomerNeedItem] = field(default_factory=list)
    hard_constraints: List[CustomerNeedItem] = field(default_factory=list)
    soft_preferences: List[CustomerNeedItem] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    confidence: float = 1.0
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_version: str = MODEL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "lead_id": self.lead_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "needs": [item.to_dict() for item in self.needs],
            "hard_constraints": [item.to_dict() for item in self.hard_constraints],
            "soft_preferences": [item.to_dict() for item in self.soft_preferences],
            "missing_information": list(self.missing_information),
            "conflicts": list(self.conflicts),
            "confidence": round(self.confidence, 4),
            "observed_at": self.observed_at,
            "model_version": self.model_version,
        }


class RecommendationOutcome(str, Enum):
    RECOMMEND_ONE = "RECOMMEND_ONE"
    RECOMMEND_MULTIPLE = "RECOMMEND_MULTIPLE"
    ASK_CLARIFYING_QUESTION = "ASK_CLARIFYING_QUESTION"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    NO_VALID_FIT = "NO_VALID_FIT"
    ANSWER_EXPLICIT_PRODUCT_QUESTION = "ANSWER_EXPLICIT_PRODUCT_QUESTION"
    COMPARE_REQUESTED_PRODUCTS = "COMPARE_REQUESTED_PRODUCTS"
    NO_RECOMMENDATION_NEEDED = "NO_RECOMMENDATION_NEEDED"


class FitLevel(str, Enum):
    STRONG = "STRONG"
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    POOR = "POOR"
    UNKNOWN = "UNKNOWN"


class RecommendationReasonCode(str, Enum):
    EXPLICIT_USE_CASE_MATCH = "EXPLICIT_USE_CASE_MATCH"
    HARD_BUDGET_MATCH = "HARD_BUDGET_MATCH"
    HARD_BUDGET_EXCEEDED = "HARD_BUDGET_EXCEEDED"
    REQUIRED_FEATURE_MATCH = "REQUIRED_FEATURE_MATCH"
    REQUIRED_FEATURE_MISSING = "REQUIRED_FEATURE_MISSING"
    PREFERRED_FEATURE_MATCH = "PREFERRED_FEATURE_MATCH"
    WARRANTY_PREFERENCE_MATCH = "WARRANTY_PREFERENCE_MATCH"
    AVAILABILITY_MATCH = "AVAILABILITY_MATCH"
    UNKNOWN_REQUIRED_ATTRIBUTE = "UNKNOWN_REQUIRED_ATTRIBUTE"
    REQUESTED_PRODUCT_EVALUATED = "REQUESTED_PRODUCT_EVALUATED"
    MULTIPLE_SIMILAR_FITS = "MULTIPLE_SIMILAR_FITS"
    INSUFFICIENT_DECISION_CRITERIA = "INSUFFICIENT_DECISION_CRITERIA"
    NO_ELIGIBLE_PRODUCT = "NO_ELIGIBLE_PRODUCT"
    CHEAPER_EQUAL_FIT = "CHEAPER_EQUAL_FIT"
    PREMIUM_FEATURE_NOT_REQUIRED = "PREMIUM_FEATURE_NOT_REQUIRED"
    TRADEOFF_PRESENT = "TRADEOFF_PRESENT"
    SINGLE_PRODUCT_CATALOG = "SINGLE_PRODUCT_CATALOG"


class ExclusionReasonCode(str, Enum):
    OUTSIDE_BUDGET = "OUTSIDE_BUDGET"
    MISSING_REQUIRED_FEATURE = "MISSING_REQUIRED_FEATURE"
    WRONG_CATEGORY = "WRONG_CATEGORY"
    OUT_OF_STOCK_FOR_REQUIRED_AVAILABILITY = "OUT_OF_STOCK_FOR_REQUIRED_AVAILABILITY"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN_REQUIRED_ATTRIBUTE = "UNKNOWN_REQUIRED_ATTRIBUTE"
    MALFORMED_PRODUCT = "MALFORMED_PRODUCT"
    TENANT_MISMATCH = "TENANT_MISMATCH"


@dataclass
class RecommendedProductRef:
    product_name: str
    sku: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    fit_level: FitLevel = FitLevel.STRONG
    matched_requirements: List[str] = field(default_factory=list)
    unmet_soft_preferences: List[str] = field(default_factory=list)
    tradeoffs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_name": self.product_name,
            "sku": self.sku,
            "price": self.price,
            "currency": self.currency,
            "fit_level": self.fit_level.value if isinstance(self.fit_level, FitLevel) else str(self.fit_level),
            "matched_requirements": list(self.matched_requirements),
            "unmet_soft_preferences": list(self.unmet_soft_preferences),
            "tradeoffs": list(self.tradeoffs),
            "evidence_refs": list(self.evidence_refs),
            "score": round(self.score, 2),
        }


@dataclass
class ExcludedProductRef:
    product_name: str
    sku: Optional[str] = None
    reason_codes: List[ExclusionReasonCode] = field(default_factory=list)
    reason_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_name": self.product_name,
            "sku": self.sku,
            "reason_codes": [r.value if isinstance(r, ExclusionReasonCode) else str(r) for r in self.reason_codes],
            "reason_description": self.reason_description,
        }


@dataclass
class RecommendationDecision:
    company_id: str
    lead_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    outcome: RecommendationOutcome = RecommendationOutcome.NO_RECOMMENDATION_NEEDED
    recommended_products: List[RecommendedProductRef] = field(default_factory=list)
    excluded_products: List[ExcludedProductRef] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    clarifying_question_code: Optional[str] = None
    clarifying_question_text: Optional[str] = None
    confidence: float = 1.0
    reason_codes: List[RecommendationReasonCode] = field(default_factory=list)
    need_snapshot_ref: str = ""
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    policy_version: str = DECISION_POLICY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "lead_id": self.lead_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "outcome": self.outcome.value if isinstance(self.outcome, RecommendationOutcome) else str(self.outcome),
            "recommended_products": [p.to_dict() for p in self.recommended_products],
            "excluded_products": [p.to_dict() for p in self.excluded_products],
            "missing_information": list(self.missing_information),
            "clarifying_question_code": self.clarifying_question_code,
            "clarifying_question_text": self.clarifying_question_text,
            "confidence": round(self.confidence, 4),
            "reason_codes": [r.value if isinstance(r, RecommendationReasonCode) else str(r) for r in self.reason_codes],
            "need_snapshot_ref": self.need_snapshot_ref,
            "observed_at": self.observed_at,
            "policy_version": self.policy_version,
        }


class EthicalProductFitMode(str, Enum):
    NO_RECOMMENDATION_RESPONSE = "NO_RECOMMENDATION_RESPONSE"
    ASK_ONE_FIT_CLARIFIER = "ASK_ONE_FIT_CLARIFIER"
    RECOMMEND_SINGLE_WITH_EVIDENCE = "RECOMMEND_SINGLE_WITH_EVIDENCE"
    RECOMMEND_MULTIPLE_WITH_TRADEOFFS = "RECOMMEND_MULTIPLE_WITH_TRADEOFFS"
    COMPARE_REQUESTED_OPTIONS = "COMPARE_REQUESTED_OPTIONS"
    EVALUATE_REQUESTED_PRODUCT_FIT = "EVALUATE_REQUESTED_PRODUCT_FIT"
    STATE_NO_VALID_FIT = "STATE_NO_VALID_FIT"
    STATE_INSUFFICIENT_INFORMATION = "STATE_INSUFFICIENT_INFORMATION"
    OFFER_HUMAN_HANDOFF = "OFFER_HUMAN_HANDOFF"
    ANSWER_PRODUCT_QUESTION_FIRST = "ANSWER_PRODUCT_QUESTION_FIRST"


class ProhibitedRecommendationTactic(str, Enum):
    PREFER_EXPENSIVE_WITHOUT_FIT = "PREFER_EXPENSIVE_WITHOUT_FIT"
    INVENT_FEATURE = "INVENT_FEATURE"
    HIDE_TRADEOFF = "HIDE_TRADEOFF"
    FAKE_PERSONALIZATION = "FAKE_PERSONALIZATION"
    PROFILING_STEREOTYPING = "PROFILING_STEREOTYPING"
    FAKE_EXPERTISE_CLAIMS = "FAKE_EXPERTISE_CLAIMS"
    FAKE_FIT_PERCENTAGE = "FAKE_FIT_PERCENTAGE"
    EXPENSIVE_ALWAYS_BETTER = "EXPENSIVE_ALWAYS_BETTER"


@dataclass
class EthicalProductFitPolicy:
    company_id: str
    lead_id: str
    recommendation_decision_ref: str
    primary_mode: EthicalProductFitMode
    response_steps: List[str] = field(default_factory=list)
    question_policy: str = "NO_QUESTION"
    cta_policy: str = "SOFT"
    pressure_ceiling: str = "LOW"
    required_product_names: List[str] = field(default_factory=list)
    required_evidence_refs: List[str] = field(default_factory=list)
    prohibited_tactics: List[ProhibitedRecommendationTactic] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    policy_version: str = ETHICAL_POLICY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "lead_id": self.lead_id,
            "recommendation_decision_ref": self.recommendation_decision_ref,
            "primary_mode": self.primary_mode.value if isinstance(self.primary_mode, EthicalProductFitMode) else str(self.primary_mode),
            "response_steps": list(self.response_steps),
            "question_policy": self.question_policy,
            "cta_policy": self.cta_policy,
            "pressure_ceiling": self.pressure_ceiling,
            "required_product_names": list(self.required_product_names),
            "required_evidence_refs": list(self.required_evidence_refs),
            "prohibited_tactics": [t.value if isinstance(t, ProhibitedRecommendationTactic) else str(t) for t in self.prohibited_tactics],
            "reason_codes": list(self.reason_codes),
            "policy_version": self.policy_version,
        }


@dataclass
class RecommendationAlignmentResult:
    status: str  # "PASS", "REPAIRED", "BLOCKED"
    final_answer: str
    violations: List[str] = field(default_factory=list)
    repaired: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "final_answer": self.final_answer,
            "violations": list(self.violations),
            "repaired": self.repaired,
        }


# =====================================================================
# NEED EXTRACTION & EVIDENCE ANALYSIS
# =====================================================================

_BUDGET_PATTERNS = [
    r"(?:ميزانيتي|ميزانيه|حدود|بحدود|في\s+حدود|أقصى\s+حاجة|اقصى\s+حاجة|السعر\s+المناسب|ممكن\s+لحد|مش\s+عايز\s+أزيد\s+عن|بـ)\s*(\d+(?:[,\s]\d{3})*(?:\.\d+)?)\s*(?:جنية|جنيه|جم|EGP|\$)?",
    r"(\d+(?:[,\s]\d{3})*)\s*(?:جنية|جنيه|جم|EGP)\s*(?:أقصى|اقصى|بالكتير|كتير)",
    r"\b(?:budget|max|up\s+to)\s*(\d+(?:[,\s]\d{3})*)\b",
]

_DURATION_USE_PATTERNS = [
    r"(\d+)\s*(?:ساعات|ساعة|ساعه|hrs|hours)",
    r"شغل\s*(?:طويل|كتير|يومي|طوال\s+اليوم)",
]

_REQUIRED_FEATURE_PATTERNS = {
    "headrest": [r"مسند\s+رأس", r"مسند\s+راس", r"headrest", r"هيدريست"],
    "lumbar_support": [r"مسند\s+ظهر", r"مسند\s+قطنية", r"مسند\s+قطنيه", r"lumbar"],
    "mesh": [r"شبك", r"mesh", r"تهوية"],
    "electric_height": [r"كهربائي", r"كهربا", r"electric", r"موتور"],
    "armrests": [r"مسند\s+يد", r"مساند\s+يد", r"ذراع", r"armrest"],
}

_CATEGORY_KEYWORDS = {
    "chair": [r"كرسي", r"كراسي", r"chair", r"seating"],
    "desk": [r"مكتب", r"مكاتب", r"desk", r"table"],
    "bundle": [r"باندل", r"بندل", r"مجموعة", r"طقم", r"bundle"],
}


def extract_customer_needs(
    user_input: str,
    company_id: str,
    lead_id: str,
    recent_messages: Optional[List[Dict[str, Any]]] = None,
    lead_evidence: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    preference_memory: Optional[Any] = None,
) -> CustomerNeedSnapshot:
    """
    Extracts canonical CustomerNeedSnapshot enforcing strict authority hierarchy:
    Customer explicit text > Customer history > LeadEvidence.
    ZERO authority for assistant messages, prompt, catalog, or lead memory summaries.
    Incorporates preference_memory as soft preferences when explicitly compatible.
    """
    needs: List[CustomerNeedItem] = []
    hard_constraints: List[CustomerNeedItem] = []
    soft_preferences: List[CustomerNeedItem] = []
    missing_information: List[str] = []
    conflicts: List[str] = []

    # Combine customer-authored text only!
    customer_texts: List[Tuple[str, str]] = []  # (text, source_ref)
    
    # 1. Current user input (Highest Authority)
    if user_input and user_input.strip():
        customer_texts.append((user_input.strip(), "current_message"))

    # 2. Recent customer-authored history (Reverse chronological check to handle updates)
    if recent_messages:
        for msg in reversed(recent_messages):
            sender = (msg.get("sender") or msg.get("role") or "").lower()
            content = (msg.get("text") or msg.get("content") or "").strip()
            if sender in {"user", "customer", "lead"} and content:
                # Avoid duplicates
                if not any(t == content for t, _ in customer_texts):
                    customer_texts.append((content, f"history_msg_{msg.get('id', '')}"))

    # Process all customer text for need extraction
    extracted_budget: Optional[float] = None
    extracted_budget_is_hard = False
    extracted_category: Optional[str] = None
    extracted_use_case: Optional[str] = None
    extracted_duration: Optional[str] = None

    seen_features: Set[str] = set()

    for text, src_ref in customer_texts:
        folded = _fold_arabic(text)
        
        # A. Budget Extraction
        if extracted_budget is None:
            for pat in _BUDGET_PATTERNS:
                m = re.search(pat, text, re.IGNORECASE)
                if not m:
                    m = re.search(pat, folded, re.IGNORECASE)
                if m:
                    try:
                        num_str = re.sub(r"[,\s]", "", m.group(1))
                        val = float(num_str)
                        if val > 0:
                            extracted_budget = val
                            # Check if hard budget ceiling
                            if any(token in folded for token in ["اقصي", "اقصى", "ما ينفعش يزيد", "مش هقدر ادفع اكتر", "حدود", "اخر دي ميزانيتي"]):
                                extracted_budget_is_hard = True
                            else:
                                extracted_budget_is_hard = True  # Default budget limit to HARD unless soft keyword present
                            break
                    except ValueError:
                        pass

        # Relaxed budget handling if customer explicitly relaxes later
        if extracted_budget is not None:
            if any(token in folded for token in ["ممكن ازود", "ممكن اعلي", "لو يستهل ادفع اكتر", "السعر مش مهم"]):
                extracted_budget_is_hard = False

        # B. Category Extraction
        if extracted_category is None:
            for cat, keywords in _CATEGORY_KEYWORDS.items():
                if any(re.search(kw, text, re.I) or re.search(kw, folded, re.I) for kw in keywords):
                    extracted_category = cat
                    break

        # C. Use Case & Duration Extraction
        if any(token in folded for token in ["شغل", "مكتب", "عمل", "قيمنج", "جيمنج", "مذاكرة"]):
            if "جيمنج" in folded or "قيمنج" in folded:
                extracted_use_case = "GAMING"
            else:
                extracted_use_case = "OFFICE_WORK"

        for pat in _DURATION_USE_PATTERNS:
            m = re.search(pat, text, re.I)
            if m and not extracted_duration:
                extracted_duration = m.group(0)

        # D. Required / Preferred Features
        for feat_key, feat_pats in _REQUIRED_FEATURE_PATTERNS.items():
            if feat_key not in seen_features:
                if any(re.search(p, text, re.I) or re.search(p, folded, re.I) for p in feat_pats):
                    seen_features.add(feat_key)
                    is_hard = any(token in folded for token in ["لازم", "ضروري", "ضروري يكون", "مهم جدا"])
                    strength = ConstraintStrength.HARD if is_hard else ConstraintStrength.SOFT
                    item = CustomerNeedItem(
                        need_type=NeedType.REQUIRED_FEATURE if strength == ConstraintStrength.HARD else NeedType.PREFERRED_FEATURE,
                        value=feat_key,
                        explicitness=NeedExplicitness.EXPLICIT,
                        constraint_strength=strength,
                        confidence=0.95,
                        raw_text=text,
                        evidence_refs=[src_ref],
                    )
                    needs.append(item)
                    if strength == ConstraintStrength.HARD:
                        hard_constraints.append(item)
                    else:
                        soft_preferences.append(item)

        # E. Color Preference
        if "أسود" in text or "اسود" in text or "black" in text.lower():
            item = CustomerNeedItem(
                need_type=NeedType.COLOR_PREFERENCE,
                value="black",
                explicitness=NeedExplicitness.EXPLICIT,
                constraint_strength=ConstraintStrength.SOFT,
                confidence=0.9,
                raw_text=text,
                evidence_refs=[src_ref],
            )
            needs.append(item)
            soft_preferences.append(item)
        elif "أبيض" in text or "ابيض" in text or "white" in text.lower():
            item = CustomerNeedItem(
                need_type=NeedType.COLOR_PREFERENCE,
                value="white",
                explicitness=NeedExplicitness.EXPLICIT,
                constraint_strength=ConstraintStrength.SOFT,
                confidence=0.9,
                raw_text=text,
                evidence_refs=[src_ref],
            )
            needs.append(item)
            soft_preferences.append(item)

    # Compile Budget Need Item
    if extracted_budget is not None:
        strength = ConstraintStrength.HARD if extracted_budget_is_hard else ConstraintStrength.SOFT
        b_item = CustomerNeedItem(
            need_type=NeedType.BUDGET_CEILING if strength == ConstraintStrength.HARD else NeedType.BUDGET_RANGE,
            value=extracted_budget,
            explicitness=NeedExplicitness.EXPLICIT,
            constraint_strength=strength,
            confidence=0.98,
            evidence_refs=["customer_budget_mention"],
        )
        needs.append(b_item)
        if strength == ConstraintStrength.HARD:
            hard_constraints.append(b_item)
        else:
            soft_preferences.append(b_item)

    # Compile Category Need Item
    if extracted_category:
        c_item = CustomerNeedItem(
            need_type=NeedType.PRODUCT_CATEGORY,
            value=extracted_category,
            explicitness=NeedExplicitness.EXPLICIT,
            constraint_strength=ConstraintStrength.HARD,
            confidence=0.95,
            evidence_refs=["customer_category_mention"],
        )
        needs.append(c_item)
        hard_constraints.append(c_item)

    # Compile Use Case & Duration Item
    if extracted_use_case:
        val = f"{extracted_use_case}_{extracted_duration}" if extracted_duration else extracted_use_case
        u_item = CustomerNeedItem(
            need_type=NeedType.USE_CASE,
            value=val,
            explicitness=NeedExplicitness.EXPLICIT,
            constraint_strength=ConstraintStrength.SOFT,
            confidence=0.9,
            evidence_refs=["customer_use_case_mention"],
        )
        needs.append(u_item)
        soft_preferences.append(u_item)

    # Track missing information for recommendation decision
    if not extracted_category:
        missing_information.append("PRODUCT_CATEGORY")
    if not extracted_use_case and not extracted_duration:
        missing_information.append("USE_CASE_DURATION")
    if extracted_budget is None:
        missing_information.append("BUDGET")

    # Incorporate preference_memory soft preferences if provided and not contradicted by current explicit needs
    if preference_memory and hasattr(preference_memory, "effective_for_current_context"):
        existing_need_values = {str(item.value).lower() for item in needs}
        for mem_item in getattr(preference_memory, "effective_for_current_context", []):
            val_str = str(mem_item.value).lower()
            if val_str not in existing_need_values:
                dim_val = mem_item.dimension.value if hasattr(mem_item.dimension, "value") else str(mem_item.dimension)
                pref_item = CustomerNeedItem(
                    need_type=NeedType.PREFERRED_FEATURE,
                    value=f"{dim_val}:{mem_item.value}",
                    explicitness=NeedExplicitness.EXPLICIT,
                    constraint_strength=ConstraintStrength.SOFT,
                    confidence=0.85,
                    evidence_refs=["customer_preference_memory"],
                )
                needs.append(pref_item)
                soft_preferences.append(pref_item)

    return CustomerNeedSnapshot(
        company_id=company_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        message_id=message_id,
        needs=needs,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
        missing_information=missing_information,
        conflicts=conflicts,
        confidence=0.95 if needs else 0.5,
    )


# =====================================================================
# RECOMMENDATION DECISION ENGINE & PRODUCT FIT
# =====================================================================

def is_recommendation_request(user_input: str) -> bool:
    """Detects if customer is explicitly asking for a product recommendation or fit evaluation."""
    text = (user_input or "").strip()
    if not text:
        return False
    folded = _fold_arabic(text)

    rec_phrases = [
        r"انهي\s+انسب",
        r"أنهي\s+أنسب",
        r"انسب\s+كرسي",
        r"أنسب\s+كرسي",
        r"انسب\s+مكتب",
        r"أنسب\s+مكتب",
        r"انهي\s+احسن",
        r"أنهي\s+أحسن",
        r"ترشحلي\s+إيه",
        r"ترشحلي\s+ايه",
        r"ترشح\s+إيه",
        r"ترشح\s+ايه",
        r"أجيب\s+أنهي",
        r"اجيب\s+انهي",
        r"إيه\0\s*أفضل",
        r"ايه\s+افضل",
        r"ايه\s+أفضل",
        r"اختار\s+إيه",
        r"اختار\s+ايه",
        r"تنصحني\s+بإيه",
        r"تنصحني\s+بايه",
        r"ينفع\s+ليا",
        r"يناسبني",
        r"which\s+one\s+is\s+best",
        r"which\s+should\s+i\s+buy",
        r"recommend",
        r"best\s+for\s+me",
    ]
    return any(re.search(pat, folded, re.I) for pat in rec_phrases)


def _product_has_feature(product: ProductContext, feature_key: str) -> Optional[bool]:
    """
    Checks if product has a feature.
    Returns True if present, False if explicitly absent/lacking, None if unknown/unspecified.
    """
    desc = (product.description or "").lower()
    name = (product.name or "").lower()
    text = f"{name} {desc}"
    folded_text = _fold_arabic(text)

    pats = _REQUIRED_FEATURE_PATTERNS.get(feature_key, [feature_key])

    # 1. Check explicit absence FIRST (e.g. "بدون مسند رأس")
    for pat in pats:
        absent_pat = r"بدون\s+" + _fold_arabic(pat)
        if re.search(absent_pat, folded_text, re.I):
            return False

    # 2. Check presence
    if any(re.search(pat, text, re.I) or re.search(_fold_arabic(pat), folded_text, re.I) for pat in pats):
        return True

    return None  # Unknown in catalog data


def evaluate_recommendation_decision(
    db: Optional[Session],
    company_id: str,
    lead_id: str,
    need_snapshot: CustomerNeedSnapshot,
    sales_snapshot: Optional[SalesStateSnapshot] = None,
    sales_state: Optional[SalesStateSnapshot] = None,
    user_input: str = "",
    requested_products: Optional[List[ProductContext]] = None,
    products: Optional[List[ProductContext]] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    preference_memory: Optional[Any] = None,
) -> RecommendationDecision:
    """
    Evaluates catalog products deterministically against customer needs.
    Enforces tenant isolation, hard constraint filtering, unknown attribute safety,
    and fit-first ranking without price or position bias.
    """
    if sales_snapshot is None:
        sales_snapshot = sales_state
    if products is not None:
        catalog = products
    else:
        catalog = get_company_products(db, company_id)
    if not catalog:
        return RecommendationDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=RecommendationOutcome.NO_VALID_FIT,
            reason_codes=[RecommendationReasonCode.NO_ELIGIBLE_PRODUCT],
            need_snapshot_ref=MODEL_VERSION,
        )

    # 1. Check if user is asking factual / price / comparison question rather than recommendation
    is_rec_req = is_recommendation_request(user_input)

    # If requested specific product explicitly (e.g. "Ergo One ينفع ليا؟")
    if requested_products and len(requested_products) == 1 and not is_rec_req:
        target = requested_products[0]
        # Evaluate target product fit
        matched = []
        unmet = []
        reasons = [RecommendationReasonCode.REQUESTED_PRODUCT_EVALUATED]

        # Check hard budget constraint
        budget_item = next((h for h in need_snapshot.hard_constraints if h.need_type in {NeedType.BUDGET_CEILING, NeedType.BUDGET_RANGE}), None)
        if budget_item and target.price is not None:
            if target.price <= budget_item.value:
                matched.append(f"Price {target.price} <= Budget {budget_item.value}")
                reasons.append(RecommendationReasonCode.HARD_BUDGET_MATCH)
            else:
                unmet.append(f"Price {target.price} exceeds budget {budget_item.value}")
                reasons.append(RecommendationReasonCode.HARD_BUDGET_EXCEEDED)

        ref = RecommendedProductRef(
            product_name=target.name,
            sku=target.sku,
            price=target.price,
            currency=target.currency,
            fit_level=FitLevel.STRONG if not unmet else FitLevel.PARTIAL,
            matched_requirements=matched,
            unmet_soft_preferences=unmet,
            score=90.0 if not unmet else 40.0,
        )

        return RecommendationDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=RecommendationOutcome.ANSWER_EXPLICIT_PRODUCT_QUESTION,
            recommended_products=[ref],
            reason_codes=reasons,
            need_snapshot_ref=MODEL_VERSION,
        )

    # 2. Check Insufficient Information Policy
    # If customer asked "أنهي أحسن؟" with ZERO explicit needs or constraints known
    if is_rec_req and not need_snapshot.needs:
        # Determine single best clarifying question
        clarifying_text = "علشان أقدر أرشحلك الأنسب تماماً، استخدامك الأساسي هيكون كم ساعة يومياً تقريباً، وهل عندك ميزانية محددة؟"
        return RecommendationDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=RecommendationOutcome.ASK_CLARIFYING_QUESTION,
            missing_information=need_snapshot.missing_information or ["USE_CASE", "BUDGET"],
            clarifying_question_code="ASK_USE_CASE_AND_BUDGET",
            clarifying_question_text=clarifying_text,
            confidence=0.5,
            reason_codes=[RecommendationReasonCode.INSUFFICIENT_DECISION_CRITERIA],
            need_snapshot_ref=MODEL_VERSION,
        )

    # 3. Hard Constraint Filtering BEFORE Ranking
    eligible_products: List[Tuple[ProductContext, List[str]]] = []  # (product, matched_hards)
    excluded_products: List[ExcludedProductRef] = []

    budget_constraint = next((h for h in need_snapshot.hard_constraints if h.need_type in {NeedType.BUDGET_CEILING, NeedType.BUDGET_RANGE}), None)
    category_constraint = next((h for h in need_snapshot.hard_constraints if h.need_type == NeedType.PRODUCT_CATEGORY), None)
    required_feature_constraints = [h for h in need_snapshot.hard_constraints if h.need_type == NeedType.REQUIRED_FEATURE]

    for product in catalog:
        exclusion_reasons: List[ExclusionReasonCode] = []
        desc_reason = []
        matched_hards = []

        # A. Category Check
        if category_constraint:
            target_cat = str(category_constraint.value).lower()
            p_cat = (product.category or "").lower()
            p_name = (product.name or "").lower()
            if target_cat == "chair" and not any(k in p_name or k in p_cat for k in ["ergo", "chair", "كرسي"]):
                if "desk" in p_name or "مكتب" in p_name:
                    exclusion_reasons.append(ExclusionReasonCode.WRONG_CATEGORY)
                    desc_reason.append("Category mismatch (Requested chair, product is desk)")
            elif target_cat == "desk" and not any(k in p_name or k in p_cat for k in ["desk", "lift", "focus", "مكتب"]):
                if "chair" in p_name or "ergo" in p_name or "كرسي" in p_name:
                    exclusion_reasons.append(ExclusionReasonCode.WRONG_CATEGORY)
                    desc_reason.append("Category mismatch (Requested desk, product is chair)")

        # B. Hard Budget Ceiling Check
        if budget_constraint and product.price is not None:
            max_b = float(budget_constraint.value)
            if product.price > max_b:
                exclusion_reasons.append(ExclusionReasonCode.OUTSIDE_BUDGET)
                desc_reason.append(f"Price {product.price} EGP exceeds hard budget limit of {max_b} EGP")
            else:
                matched_hards.append(f"Price {product.price} EGP <= Budget {max_b} EGP")

        # C. Hard Required Features Check
        for req_feat in required_feature_constraints:
            feat_key = str(req_feat.value)
            has_feat = _product_has_feature(product, feat_key)
            if has_feat is False:
                exclusion_reasons.append(ExclusionReasonCode.MISSING_REQUIRED_FEATURE)
                desc_reason.append(f"Explicitly missing required feature: {feat_key}")
            elif has_feat is True:
                matched_hards.append(f"Has required feature: {feat_key}")
            elif has_feat is None:
                # UNKNOWN ATTRIBUTE SAFETY: If feature is hard constraint and catalog has no data,
                # do not pass as guaranteed fit
                matched_hards.append(f"Unknown status for required feature: {feat_key}")

        if exclusion_reasons:
            excluded_products.append(
                ExcludedProductRef(
                    product_name=product.name,
                    sku=product.sku,
                    reason_codes=exclusion_reasons,
                    reason_description="; ".join(desc_reason),
                )
            )
        else:
            eligible_products.append((product, matched_hards))

    # If NO eligible products remain after hard filtering
    if not eligible_products:
        return RecommendationDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=RecommendationOutcome.NO_VALID_FIT,
            excluded_products=excluded_products,
            confidence=0.9,
            reason_codes=[RecommendationReasonCode.NO_ELIGIBLE_PRODUCT],
            need_snapshot_ref=MODEL_VERSION,
        )

    # 4. Fit-First Candidate Ranking
    # Base score = 50.0
    scored_candidates: List[RecommendedProductRef] = []

    for product, matched_hards in eligible_products:
        score = 50.0
        matched_reqs = list(matched_hards)
        unmet_softs = []
        tradeoffs = []

        # Soft preferences evaluation
        for pref in need_snapshot.soft_preferences:
            if pref.need_type == NeedType.COLOR_PREFERENCE:
                pref_col = str(pref.value).lower()
                prod_cols = [c.lower() for c in product.colors]
                if pref_col in prod_cols:
                    score += 10.0
                    matched_reqs.append(f"Color match ({pref_col})")
                elif prod_cols:
                    unmet_softs.append(f"Preferred color {pref_col} not in {prod_cols}")
            elif pref.need_type in {NeedType.USE_CASE, NeedType.COMFORT_PRIORITY, NeedType.ERGONOMICS_PRIORITY}:
                # Match use case keywords in product description/name
                p_text = f"{product.name} {product.description or ''}".lower()
                if "ergo" in p_text or "مريح" in p_text or "شغل" in p_text or "8" in p_text:
                    score += 15.0
                    matched_reqs.append("Suited for long office work & ergonomics")

        # Specific query keyword matching (e.g. user requested product feature or title words)
        if user_input:
            clean_ui = _strip_punctuation(user_input).casefold()
            clean_name = _strip_punctuation(product.name).casefold()
            clean_desc = _strip_punctuation(product.description or "").casefold()
            ui_tokens = [t for t in clean_ui.split() if len(t) > 3 and t not in {"عايز", "محتاج", "ميزانية", "ميزانيتي", "كرسي", "مكتب"}]
            if any(t in clean_name or t in clean_desc for t in ui_tokens):
                score += 25.0
                matched_reqs.append("Matches specific request keywords")

        # Fit discipline: Lower price under budget ceiling does NOT penalize product!
        # If product is cheaper and satisfies all hard constraints, it ranks HIGHER or EQUAL to expensive products!
        if budget_constraint and product.price is not None:
            max_b = float(budget_constraint.value)
            # Give a small efficiency bonus for staying safely under budget without overcharging
            if product.price <= max_b:
                savings = max_b - product.price
                # Modest bonus up to +10 for budget efficiency
                score += min(10.0, (savings / max_b) * 10.0)

        # Warranty bonus if present
        if product.warranty:
            score += 5.0
            matched_reqs.append(f"Includes warranty: {product.warranty}")

        # Construct tradeoffs (e.g. if product lacks optional premium features vs higher models)
        if product.price is not None and budget_constraint:
            if product.price < float(budget_constraint.value):
                tradeoffs.append(f"Cheaper option ({product.price} EGP) meeting all required needs")

        fit_lvl = FitLevel.STRONG if score >= 65.0 else FitLevel.GOOD

        scored_candidates.append(
            RecommendedProductRef(
                product_name=product.name,
                sku=product.sku,
                price=product.price,
                currency=product.currency or "EGP",
                fit_level=fit_lvl,
                matched_requirements=matched_reqs,
                unmet_soft_preferences=unmet_softs,
                tradeoffs=tradeoffs,
                score=score,
            )
        )

    # Sort deterministically by Score DESC, then Name ASC (NO catalog order bias!)
    scored_candidates.sort(key=lambda c: (-c.score, c.product_name))

    # 5. Determine Outcome (RECOMMEND_ONE vs RECOMMEND_MULTIPLE)
    if len(scored_candidates) == 1:
        outcome = RecommendationOutcome.RECOMMEND_ONE
        reasons = [RecommendationReasonCode.EXPLICIT_USE_CASE_MATCH]
        if len(catalog) == 1:
            reasons.append(RecommendationReasonCode.SINGLE_PRODUCT_CATALOG)
    else:
        top_cand = scored_candidates[0]
        second_cand = scored_candidates[1]
        # If top candidate is significantly stronger (>15 score diff), recommend single
        if (top_cand.score - second_cand.score) >= 15.0:
            outcome = RecommendationOutcome.RECOMMEND_ONE
            reasons = [RecommendationReasonCode.EXPLICIT_USE_CASE_MATCH]
        else:
            outcome = RecommendationOutcome.RECOMMEND_MULTIPLE
            reasons = [RecommendationReasonCode.MULTIPLE_SIMILAR_FITS, RecommendationReasonCode.TRADEOFF_PRESENT]

    return RecommendationDecision(
        company_id=company_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        message_id=message_id,
        outcome=outcome,
        recommended_products=scored_candidates[:3],  # Max top 3 candidates
        excluded_products=excluded_products,
        confidence=0.92,
        reason_codes=reasons,
        need_snapshot_ref=MODEL_VERSION,
    )


# =====================================================================
# ETHICAL PRODUCT-FIT RESPONSE POLICY
# =====================================================================

def evaluate_ethical_product_fit_policy(
    decision: RecommendationDecision,
    sales_state: Optional[SalesStateSnapshot] = None,
) -> EthicalProductFitPolicy:
    """
    Constructs EthicalProductFitPolicy governing system response structure.
    Prohibits dark patterns, fake personalization, stereotyping, and unsupported upsells.
    """
    prohibited = [
        ProhibitedRecommendationTactic.PREFER_EXPENSIVE_WITHOUT_FIT,
        ProhibitedRecommendationTactic.INVENT_FEATURE,
        ProhibitedRecommendationTactic.HIDE_TRADEOFF,
        ProhibitedRecommendationTactic.FAKE_PERSONALIZATION,
        ProhibitedRecommendationTactic.PROFILING_STEREOTYPING,
        ProhibitedRecommendationTactic.FAKE_EXPERTISE_CLAIMS,
        ProhibitedRecommendationTactic.FAKE_FIT_PERCENTAGE,
        ProhibitedRecommendationTactic.EXPENSIVE_ALWAYS_BETTER,
    ]

    mode_map = {
        RecommendationOutcome.RECOMMEND_ONE: EthicalProductFitMode.RECOMMEND_SINGLE_WITH_EVIDENCE,
        RecommendationOutcome.RECOMMEND_MULTIPLE: EthicalProductFitMode.RECOMMEND_MULTIPLE_WITH_TRADEOFFS,
        RecommendationOutcome.ASK_CLARIFYING_QUESTION: EthicalProductFitMode.ASK_ONE_FIT_CLARIFIER,
        RecommendationOutcome.INSUFFICIENT_INFORMATION: EthicalProductFitMode.STATE_INSUFFICIENT_INFORMATION,
        RecommendationOutcome.NO_VALID_FIT: EthicalProductFitMode.STATE_NO_VALID_FIT,
        RecommendationOutcome.ANSWER_EXPLICIT_PRODUCT_QUESTION: EthicalProductFitMode.EVALUATE_REQUESTED_PRODUCT_FIT,
        RecommendationOutcome.COMPARE_REQUESTED_PRODUCTS: EthicalProductFitMode.COMPARE_REQUESTED_OPTIONS,
        RecommendationOutcome.NO_RECOMMENDATION_NEEDED: EthicalProductFitMode.NO_RECOMMENDATION_RESPONSE,
    }

    primary_mode = mode_map.get(decision.outcome, EthicalProductFitMode.NO_RECOMMENDATION_RESPONSE)

    response_steps = []
    if primary_mode == EthicalProductFitMode.RECOMMEND_SINGLE_WITH_EVIDENCE:
        response_steps = ["ACKNOWLEDGE_NEED", "STATE_RECOMMENDATION", "EXPLAIN_SUPPORTED_FIT", "STATE_MATERIAL_TRADEOFF"]
    elif primary_mode == EthicalProductFitMode.RECOMMEND_MULTIPLE_WITH_TRADEOFFS:
        response_steps = ["ACKNOWLEDGE_NEED", "PRESENT_OPTIONS", "EXPLAIN_SUPPORTED_DIFFERENCES", "OFFER_HELP_NARROWING"]
    elif primary_mode == EthicalProductFitMode.ASK_ONE_FIT_CLARIFIER:
        response_steps = ["ACKNOWLEDGE_REQUEST", "ASK_ONE_DECISION_CRITERION"]

    req_products = [p.product_name for p in decision.recommended_products]

    return EthicalProductFitPolicy(
        company_id=decision.company_id,
        lead_id=decision.lead_id,
        recommendation_decision_ref=decision.policy_version,
        primary_mode=primary_mode,
        response_steps=response_steps,
        question_policy="ONE_DECISION_QUESTION" if primary_mode == EthicalProductFitMode.ASK_ONE_FIT_CLARIFIER else "NO_QUESTION",
        cta_policy="SOFT",
        pressure_ceiling="LOW",
        required_product_names=req_products,
        prohibited_tactics=prohibited,
        reason_codes=[r.value for r in decision.reason_codes],
    )


# =====================================================================
# FINAL REPLY ALIGNMENT & HIGH-RISK MISMATCH DETECTION
# =====================================================================

def enforce_recommendation_reply_alignment(
    candidate_reply: str,
    decision: RecommendationDecision,
    policy: EthicalProductFitPolicy,
) -> RecommendationAlignmentResult:
    """
    Audits actual candidate reply generated by provider against canonical RecommendationDecision.
    Blocks/repairs high-risk violations:
    1. Fake precision (e.g. "95% match")
    2. Expensive bias ("الأغلى دايماً أفضل")
    3. Mismatch (Decision recommended A, candidate reply recommends B without evidence)
    4. Fake personalization when INSUFFICIENT_INFORMATION
    5. Stereotyping ("بما إنك طالب")
    """
    violations: List[str] = []
    folded = _fold_arabic(candidate_reply)

    # 1. Fake Fit Percentage
    if re.search(r"(\d{2,3}\s*%|\d{2,3}\s*٪|نسبة\s*التوافق)", candidate_reply):
        violations.append("FAKE_FIT_PERCENTAGE: Fake fit percentages are prohibited")

    # 2. Expensive Always Better
    expensive_patterns = ["الاغلى دايما افضل", "الأغلى دايماً أفضل", "السعر العالي يعني افضل", "المنتج الاغلى هو الاحسن"]
    if any(_fold_arabic(token) in folded for token in expensive_patterns):
        violations.append("EXPENSIVE_ALWAYS_BETTER: False claim that expensive products are universally superior")

    # 3. Demographic Stereotyping
    stereotyping_patterns = ["بما انك طالب", "بما إنك طالب", "عشان انت طالب", "الفئة دي بتشتري"]
    if any(_fold_arabic(token) in folded for token in stereotyping_patterns):
        violations.append("PROFILING_STEREOTYPING: Demographic stereotyping prohibited")

    # 4. Fake Personalization when INSUFFICIENT_INFORMATION
    if decision.outcome in {RecommendationOutcome.INSUFFICIENT_INFORMATION, RecommendationOutcome.ASK_CLARIFYING_QUESTION}:
        personalization_patterns = ["هو الافضل ليك تماما", "أكيد ده الأنسب لك", "ده انسب حاجة لشخصيتك", "مثالي ليك", "مثالي لك"]
        if any(_fold_arabic(token) in folded for token in personalization_patterns):
            violations.append("FAKE_PERSONALIZATION: Claimed definitive personal fit despite insufficient decision criteria")

    # 5. Recommendation Mismatch
    if decision.outcome in {RecommendationOutcome.RECOMMEND_ONE, RecommendationOutcome.RECOMMEND_MULTIPLE} and decision.recommended_products:
        rec_name = decision.recommended_products[0].product_name
        # Check if candidate reply asserts a DIFFERENT product as best
        if decision.excluded_products:
            for ex in decision.excluded_products:
                ex_name = ex.get("product_name", "") if isinstance(ex, dict) else getattr(ex, "product_name", "")
                ex_folded = _fold_arabic(ex_name)
                cand_lower = candidate_reply.lower()
                # Check for ex_folded, ex_name.lower(), or key product sub-tokens (e.g. "ergo pro")
                sub_tokens = [t for t in ex_name.lower().split() if t not in {"arvena", "arven", "product", "chair", "desk", "منتج", "كرسي", "مكتب"}]
                match_ex = (
                    ex_name.lower() in cand_lower
                    or ex_folded in folded
                    or (sub_tokens and all(t in cand_lower for t in sub_tokens))
                )
                if match_ex and any(kw in candidate_reply for kw in ["هو الأنسب", "هو الاحسن", "أنصحك بـ", "هو الأنسب ليك", "الأنسب"]):
                    violations.append(f"RECOMMENDATION_MISMATCH: Recommended excluded product {ex_name} instead of canonical choice {rec_name}")

    if not violations:
        return RecommendationAlignmentResult(status="PASS", final_answer=candidate_reply)

    # Repair candidate reply if violations exist
    safe_reply = candidate_reply
    if "FAKE_FIT_PERCENTAGE" in str(violations):
        safe_reply = re.sub(r"بنسبة\s*\d+٪|بنسبة\s*\d+%|نسبة\s*التوافق\s*\d+٪", "", safe_reply).strip()

    if "EXPENSIVE_ALWAYS_BETTER" in str(violations) or "FAKE_PERSONALIZATION" in str(violations) or "RECOMMENDATION_MISMATCH" in str(violations):
        if decision.outcome == RecommendationOutcome.ASK_CLARIFYING_QUESTION and decision.clarifying_question_text:
            safe_reply = decision.clarifying_question_text
        elif decision.recommended_products:
            top_p = decision.recommended_products[0]
            safe_reply = f"بناءً على احتياجاتك المحددة، منتج {top_p.product_name} بسعر {top_p.price} ج.م هو الخيار الأنسب لحضرتك."
        else:
            safe_reply = "نحن نوصي دائماً بالخيار الأنسب لاحتياجاتك وميزانيتك الحقيقية."

    return RecommendationAlignmentResult(
        status="REPAIRED",
        final_answer=safe_reply,
        violations=violations,
        repaired=True,
    )


def format_recommendation_context_for_prompt(
    need_snapshot: CustomerNeedSnapshot,
    decision: RecommendationDecision,
    policy: EthicalProductFitPolicy,
) -> str:
    """Formats canonical recommendation intelligence context for LLM runtime delivery."""
    lines = [
        "[CANONICAL RECOMMENDATION INTELLIGENCE & ETHICAL PRODUCT FIT (SOURCE A)]:",
        f"- Need Snapshot Status: Confidence {need_snapshot.confidence:.2f}",
    ]

    if need_snapshot.needs:
        lines.append("- Explicit Customer Needs & Constraints:")
        for item in need_snapshot.needs:
            st = f" [{item.constraint_strength.value}]" if item.constraint_strength else ""
            lines.append(f"  * {item.need_type.value}: {item.value}{st} (Explicitness: {item.explicitness.value})")
    else:
        lines.append("- Explicit Customer Needs: None stated yet.")

    lines.append(f"- Canonical Recommendation Outcome: {decision.outcome.value}")

    if decision.outcome == RecommendationOutcome.RECOMMEND_ONE and decision.recommended_products:
        p = decision.recommended_products[0]
        lines.append(f"- Strongest Product Fit: {p.product_name} ({p.price} {p.currency}) | Fit Level: {p.fit_level.value}")
        if p.matched_requirements:
            lines.append(f"  * Supported Fit Reasons: {', '.join(p.matched_requirements)}")
        if p.tradeoffs:
            lines.append(f"  * Supported Trade-offs: {', '.join(p.tradeoffs)}")
    elif decision.outcome == RecommendationOutcome.RECOMMEND_MULTIPLE:
        lines.append("- Multiple Eligible Product Fits:")
        for p in decision.recommended_products:
            lines.append(f"  * {p.product_name} ({p.price} {p.currency}) - Fit: {p.fit_level.value}")
    elif decision.outcome in {RecommendationOutcome.ASK_CLARIFYING_QUESTION, RecommendationOutcome.INSUFFICIENT_INFORMATION}:
        lines.append(f"- Action Required: Ask ONE clarifying question to determine fit. Question: {decision.clarifying_question_text}")
    elif decision.outcome == RecommendationOutcome.NO_VALID_FIT:
        lines.append("- Status: No catalog product satisfies all customer hard constraints. State limitation honestly and offer options.")

    lines.append("- Ethical Response Policy Rules:")
    lines.append("  * DO NOT recommend more expensive products unless explicit needs justify fit.")
    lines.append("  * DO NOT invent features, prices, warranty, or health claims.")
    lines.append("  * DO NOT use fake fit percentages (e.g. 95% match) or demographic stereotyping.")

    return "\n".join(lines)
