"""
Customer Preference Memory & Relationship Intelligence Service for VELOR.

Canonical longitudinal memory layer for customer-authored preferences and relationship context.
Enforces strict source authority hierarchy, explicit vs inferred distinction, stable vs temporary distinction,
scope determination, supersession, revocation, staleness evaluation, relationship continuity,
and strict anti-poisoning (zero authority for assistant statements, prompts, catalog, or unverified claims).
"""

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

log = logging.getLogger("velor.customer_memory")

MODEL_VERSION = "velor_preference_memory_v1"
RELATIONSHIP_MODEL_VERSION = "velor_relationship_context_v1"


class PreferenceDimension(str, Enum):
    PRODUCT = "PRODUCT"
    PRODUCT_CATEGORY = "PRODUCT_CATEGORY"
    BRAND = "BRAND"
    FEATURE = "FEATURE"
    COLOR = "COLOR"
    SIZE = "SIZE"
    DIMENSION = "DIMENSION"
    CAPACITY = "CAPACITY"
    MATERIAL = "MATERIAL"
    STYLE = "STYLE"
    USE_CASE = "USE_CASE"
    COMFORT = "COMFORT"
    ERGONOMICS = "ERGONOMICS"
    DURABILITY = "DURABILITY"
    WARRANTY = "WARRANTY"
    DELIVERY = "DELIVERY"
    PAYMENT_METHOD = "PAYMENT_METHOD"
    PRICE_RANGE = "PRICE_RANGE"
    BUDGET_RANGE = "BUDGET_RANGE"
    AVAILABILITY = "AVAILABILITY"
    QUANTITY_PATTERN = "QUANTITY_PATTERN"
    OTHER = "OTHER"


class PreferencePolarity(str, Enum):
    PREFER = "PREFER"
    AVOID = "AVOID"
    REQUIRE = "REQUIRE"
    EXCLUDE = "EXCLUDE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class PreferenceStability(str, Enum):
    STABLE = "STABLE"
    TEMPORARY = "TEMPORARY"
    CURRENT_CONTEXT_ONLY = "CURRENT_CONTEXT_ONLY"
    UNKNOWN = "UNKNOWN"


class PreferenceExplicitness(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED_HYPOTHESIS = "INFERRED_HYPOTHESIS"
    OBSERVED_PATTERN = "OBSERVED_PATTERN"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class PreferenceScope(str, Enum):
    GLOBAL = "GLOBAL"
    CATEGORY = "CATEGORY"
    PRODUCT = "PRODUCT"
    CURRENT_PURCHASE = "CURRENT_PURCHASE"
    CONVERSATION = "CONVERSATION"
    UNKNOWN = "UNKNOWN"


class PreferenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"


class RelationshipContinuity(str, Enum):
    NEW = "NEW"
    RETURNING = "RETURNING"
    REPEAT_BUYER = "REPEAT_BUYER"
    UNKNOWN = "UNKNOWN"


@dataclass
class CustomerPreferenceMemoryItem:
    memory_id: str
    company_id: str
    lead_id: str
    dimension: PreferenceDimension
    polarity: PreferencePolarity
    value: str
    scope: PreferenceScope = PreferenceScope.GLOBAL
    scope_ref: Optional[str] = None
    explicitness: PreferenceExplicitness = PreferenceExplicitness.EXPLICIT
    stability: PreferenceStability = PreferenceStability.STABLE
    confidence: float = 1.0
    status: PreferenceStatus = PreferenceStatus.ACTIVE
    evidence_refs: List[str] = field(default_factory=list)
    first_observed_at: Optional[str] = None
    last_confirmed_at: Optional[str] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    reason_codes: List[str] = field(default_factory=list)
    model_version: str = MODEL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["dimension"] = self.dimension.value if isinstance(self.dimension, Enum) else str(self.dimension)
        d["polarity"] = self.polarity.value if isinstance(self.polarity, Enum) else str(self.polarity)
        d["stability"] = self.stability.value if isinstance(self.stability, Enum) else str(self.stability)
        d["explicitness"] = self.explicitness.value if isinstance(self.explicitness, Enum) else str(self.explicitness)
        d["scope"] = self.scope.value if isinstance(self.scope, Enum) else str(self.scope)
        d["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomerPreferenceMemoryItem":
        data = dict(data)
        if "dimension" in data and isinstance(data["dimension"], str):
            try:
                data["dimension"] = PreferenceDimension(data["dimension"])
            except ValueError:
                data["dimension"] = PreferenceDimension.OTHER
        if "polarity" in data and isinstance(data["polarity"], str):
            try:
                data["polarity"] = PreferencePolarity(data["polarity"])
            except ValueError:
                data["polarity"] = PreferencePolarity.UNKNOWN
        if "stability" in data and isinstance(data["stability"], str):
            try:
                data["stability"] = PreferenceStability(data["stability"])
            except ValueError:
                data["stability"] = PreferenceStability.UNKNOWN
        if "explicitness" in data and isinstance(data["explicitness"], str):
            try:
                data["explicitness"] = PreferenceExplicitness(data["explicitness"])
            except ValueError:
                data["explicitness"] = PreferenceExplicitness.UNKNOWN
        if "scope" in data and isinstance(data["scope"], str):
            try:
                data["scope"] = PreferenceScope(data["scope"])
            except ValueError:
                data["scope"] = PreferenceScope.UNKNOWN
        if "status" in data and isinstance(data["status"], str):
            try:
                data["status"] = PreferenceStatus(data["status"])
            except ValueError:
                data["status"] = PreferenceStatus.UNKNOWN
        return cls(**data)


@dataclass
class CustomerPreferenceMemorySnapshot:
    company_id: str
    lead_id: str
    active_preferences: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    temporary_preferences: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    inferred_hypotheses: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    stale_items: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    conflicts: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    revoked_items: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    effective_for_current_context: List[CustomerPreferenceMemoryItem] = field(default_factory=list)
    memory_version: str = MODEL_VERSION
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "lead_id": self.lead_id,
            "active_preferences": [x.to_dict() for x in self.active_preferences],
            "temporary_preferences": [x.to_dict() for x in self.temporary_preferences],
            "inferred_hypotheses": [x.to_dict() for x in self.inferred_hypotheses],
            "stale_items": [x.to_dict() for x in self.stale_items],
            "conflicts": [x.to_dict() for x in self.conflicts],
            "revoked_items": [x.to_dict() for x in self.revoked_items],
            "effective_for_current_context": [x.to_dict() for x in self.effective_for_current_context],
            "memory_version": self.memory_version,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomerPreferenceMemorySnapshot":
        data = dict(data)
        for key in [
            "active_preferences",
            "temporary_preferences",
            "inferred_hypotheses",
            "stale_items",
            "conflicts",
            "revoked_items",
            "effective_for_current_context",
        ]:
            if key in data and isinstance(data[key], list):
                data[key] = [
                    CustomerPreferenceMemoryItem.from_dict(item) if isinstance(item, dict) else item
                    for item in data[key]
                ]
        return cls(**data)


@dataclass
class RelationshipContextSnapshot:
    company_id: str
    lead_id: str
    continuity_status: RelationshipContinuity = RelationshipContinuity.NEW
    first_customer_interaction_at: Optional[str] = None
    last_customer_interaction_at: Optional[str] = None
    prior_customer_message_count: int = 0
    claimed_prior_purchase: bool = False
    verified_prior_purchases: List[str] = field(default_factory=list)
    prior_order_refs: List[str] = field(default_factory=list)
    prior_discussed_product_refs: List[str] = field(default_factory=list)
    active_preference_count: int = 0
    evidence_refs: List[str] = field(default_factory=list)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_version: str = RELATIONSHIP_MODEL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["continuity_status"] = (
            self.continuity_status.value if isinstance(self.continuity_status, Enum) else str(self.continuity_status)
        )
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RelationshipContextSnapshot":
        data = dict(data)
        if "continuity_status" in data and isinstance(data["continuity_status"], str):
            try:
                data["continuity_status"] = RelationshipContinuity(data["continuity_status"])
            except ValueError:
                data["continuity_status"] = RelationshipContinuity.UNKNOWN
        return cls(**data)


# Bounded vocabulary mappings for deterministic extraction
COLOR_VOCABULARY = {
    "أسود": "black",
    "اسود": "black",
    "black": "black",
    "أبيض": "white",
    "ابيض": "white",
    "white": "white",
    "رمادي": "gray",
    "رمادى": "gray",
    "gray": "gray",
    "grey": "gray",
    "أحمر": "red",
    "احمر": "red",
    "red": "red",
    "أزرق": "blue",
    "ازرق": "blue",
    "blue": "blue",
    "بني": "brown",
    "بنى": "brown",
    "brown": "brown",
    "اخضر": "green",
    "أخضر": "green",
    "green": "green",
    "كحلي": "navy",
    "بيج": "beige",
    "beige": "beige",
}

MATERIAL_VOCABULARY = {
    "جلد": "leather",
    "leather": "leather",
    "قماش": "fabric",
    "fabric": "fabric",
    "خشب": "wood",
    "wood": "wood",
    "معدن": "metal",
    "metal": "metal",
    "شبك": "mesh",
    "mesh": "mesh",
}

FEATURE_VOCABULARY = {
    "headrest": "headrest",
    "مسند رأس": "headrest",
    "مسند راس": "headrest",
    "lumbar": "lumbar_support",
    "دعامة ظهر": "lumbar_support",
    "مسند ظهر": "lumbar_support",
    "armrest": "armrest",
    "مسند يد": "armrest",
    "مسند ايد": "armrest",
    "ضمان": "warranty",
    "توصيل": "delivery",
}

# Arabic/English Revocation keywords
REVOCATION_PATTERNS = [
    r"انس[ىا]?\s+موضوع",
    r"forget\s+(about\s+)?my\s+old",
    r"forget\s+that",
    r"امسح\s+اللي\s+قلته",
    r"اللون\s+مش\s+مهم",
    r"مش\s+فارق\s+اللون",
    r"color\s+doesn'?t\s+matter",
    r"غيرت\s+رأيي",
    r"changed\s+my\s+mind",
    r"مش\s+عايزك\s+تعتبر",
    r"don'?t\s+treat\s+my\s+old",
    r"المرة\s+دي\s+مش\s+فارق",
]


def _normalize_str(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    # Normalize Arabic characters
    t = re.sub(r"[أإآ]", "ا", t)
    t = re.sub(r"ى", "ي", t)
    t = re.sub(r"ؤ", "و", t)
    t = re.sub(r"ئ", "ي", t)
    return t


def _generate_memory_id(company_id: str, lead_id: str, dimension: str, value: str, scope: str) -> str:
    raw = f"{company_id}:{lead_id}:{dimension}:{value}:{scope}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def extract_preference_candidates_from_text(
    text: str,
    company_id: str,
    lead_id: str,
    source_ref: str,
    observed_time: str,
) -> Tuple[List[CustomerPreferenceMemoryItem], List[str], List[Dict[str, Any]]]:
    """
    Extracts CustomerPreferenceMemoryItem candidates from explicit customer-authored text ONLY.
    Returns (extracted_items, revoked_dimensions, explicit_signals).
    """
    items: List[CustomerPreferenceMemoryItem] = []
    revoked_dimensions: List[str] = []
    explicit_signals: List[Dict[str, Any]] = []

    norm = _normalize_str(text)
    if not norm:
        return items, revoked_dimensions, explicit_signals

    # Check for Revocation triggers first
    for rev_pat in REVOCATION_PATTERNS:
        if re.search(rev_pat, norm):
            if "لون" in norm or "color" in norm:
                revoked_dimensions.append(PreferenceDimension.COLOR.value)
            if "ميزانية" in norm or "budget" in norm or "سعر" in norm or "price" in norm:
                revoked_dimensions.append(PreferenceDimension.BUDGET_RANGE.value)
            if "جلد" in norm or "leather" in norm or "خامة" in norm or "material" in norm:
                revoked_dimensions.append(PreferenceDimension.MATERIAL.value)
            if not revoked_dimensions:
                # General revocation if ambiguous
                revoked_dimensions.append("ALL_TEMPORARY")

    # 1. COLOR PREFERENCE EXTRACTION
    for term, canon_val in COLOR_VOCABULARY.items():
        if term in norm:
            # Check context around term
            is_always = any(w in norm for w in ["دايما", "دايمًا", "always", "عادة", "usually"])
            is_avoid = any(w in norm for w in ["مش بحب", "بكره", "مش عايز", "لا افور", "don't like", "avoid", "not"])
            is_this_time = any(w in norm for w in ["المرة دي", "دلوقتي", "this time", "for now"])
            is_category_scoped = any(w in norm for w in ["في الكراسي", "في المكاتب", "for chairs", "in chairs"])

            polarity = PreferencePolarity.AVOID if is_avoid else PreferencePolarity.PREFER
            stability = (
                PreferenceStability.STABLE
                if is_always
                else (PreferenceStability.CURRENT_CONTEXT_ONLY if is_this_time else PreferenceStability.STABLE)
            )
            scope = (
                PreferenceScope.CATEGORY
                if is_category_scoped
                else (
                    PreferenceScope.CURRENT_PURCHASE
                    if is_this_time
                    else PreferenceScope.GLOBAL
                )
            )

            mem_id = _generate_memory_id(company_id, lead_id, PreferenceDimension.COLOR.value, canon_val, scope.value)
            item = CustomerPreferenceMemoryItem(
                memory_id=mem_id,
                company_id=company_id,
                lead_id=str(lead_id),
                dimension=PreferenceDimension.COLOR,
                polarity=polarity,
                value=canon_val,
                scope=scope,
                scope_ref="office_chair" if is_category_scoped else None,
                explicitness=PreferenceExplicitness.EXPLICIT,
                stability=stability,
                confidence=0.95,
                status=PreferenceStatus.ACTIVE,
                evidence_refs=[source_ref],
                first_observed_at=observed_time,
                last_confirmed_at=observed_time,
                reason_codes=["EXPLICIT_CUSTOMER_STATEMENT"],
            )
            items.append(item)
            explicit_signals.append({"type": "COLOR", "value": canon_val, "stability": stability.value})

    # 2. BUDGET / PRICE RANGE EXTRACTION
    # Match numbers like 7000, 7,000, 11000 EGP, 5000ج
    budget_match = re.search(r"(?:ميزانيتي|ميزانية|budget|حدود|معايا|اقصى|أقصى)\s*(?:حاجة|السعر)?\s*[:=]?\s*(\d{4,6})", norm)
    if not budget_match:
        budget_match = re.search(r"(\d{4,6})\s*(?:جنيه|egp|ج|ريال)?", norm)
        # Verify it looks like budget context
        if budget_match and not any(k in norm for k in ["ميزانية", "budget", "سعر", "حدود", "معايا", "اخرى", "آخري", "اقصى", "أقصى"]):
            budget_match = None

    if budget_match:
        try:
            val_num = int(budget_match.group(1))
            if 500 <= val_num <= 1000000:
                is_always_budget = any(w in norm for w in ["عادة", "دايما", "usually", "always"])
                is_current_only = any(w in norm for w in ["المرة دي", "دلوقتي", "this time", "for now", "معايا"])
                
                stability = (
                    PreferenceStability.STABLE
                    if is_always_budget
                    else PreferenceStability.CURRENT_CONTEXT_ONLY
                )
                scope = PreferenceScope.CURRENT_PURCHASE if not is_always_budget else PreferenceScope.GLOBAL

                mem_id = _generate_memory_id(
                    company_id, lead_id, PreferenceDimension.BUDGET_RANGE.value, str(val_num), scope.value
                )
                item = CustomerPreferenceMemoryItem(
                    memory_id=mem_id,
                    company_id=company_id,
                    lead_id=str(lead_id),
                    dimension=PreferenceDimension.BUDGET_RANGE,
                    polarity=PreferencePolarity.REQUIRE,
                    value=str(val_num),
                    scope=scope,
                    explicitness=PreferenceExplicitness.EXPLICIT,
                    stability=stability,
                    confidence=0.9,
                    status=PreferenceStatus.ACTIVE,
                    evidence_refs=[source_ref],
                    first_observed_at=observed_time,
                    last_confirmed_at=observed_time,
                    reason_codes=["EXPLICIT_BUDGET_STATEMENT"],
                )
                items.append(item)
                explicit_signals.append({"type": "BUDGET", "value": str(val_num), "stability": stability.value})
        except Exception:
            pass

    # 3. MATERIAL EXTRACTION
    for term, canon_val in MATERIAL_VOCABULARY.items():
        if term in norm:
            is_avoid = any(w in norm for w in ["مش بحب", "مش عايز", "بكره", "don't like", "avoid"])
            polarity = PreferencePolarity.AVOID if is_avoid else PreferencePolarity.PREFER
            mem_id = _generate_memory_id(
                company_id, lead_id, PreferenceDimension.MATERIAL.value, canon_val, PreferenceScope.GLOBAL.value
            )
            item = CustomerPreferenceMemoryItem(
                memory_id=mem_id,
                company_id=company_id,
                lead_id=str(lead_id),
                dimension=PreferenceDimension.MATERIAL,
                polarity=polarity,
                value=canon_val,
                scope=PreferenceScope.GLOBAL,
                explicitness=PreferenceExplicitness.EXPLICIT,
                stability=PreferenceStability.STABLE,
                confidence=0.9,
                status=PreferenceStatus.ACTIVE,
                evidence_refs=[source_ref],
                first_observed_at=observed_time,
                last_confirmed_at=observed_time,
                reason_codes=["EXPLICIT_MATERIAL_STATEMENT"],
            )
            items.append(item)

    # 4. FEATURE EXTRACTION
    for term, canon_val in FEATURE_VOCABULARY.items():
        if term in norm:
            is_always = any(w in norm for w in ["دايما", "دايمًا", "always"])
            polarity = PreferencePolarity.REQUIRE if "لازم" in norm or "must" in norm else PreferencePolarity.PREFER
            stability = PreferenceStability.STABLE if is_always else PreferenceStability.CURRENT_CONTEXT_ONLY
            mem_id = _generate_memory_id(
                company_id, lead_id, PreferenceDimension.FEATURE.value, canon_val, PreferenceScope.GLOBAL.value
            )
            item = CustomerPreferenceMemoryItem(
                memory_id=mem_id,
                company_id=company_id,
                lead_id=str(lead_id),
                dimension=PreferenceDimension.FEATURE,
                polarity=polarity,
                value=canon_val,
                scope=PreferenceScope.GLOBAL,
                explicitness=PreferenceExplicitness.EXPLICIT,
                stability=stability,
                confidence=0.9,
                status=PreferenceStatus.ACTIVE,
                evidence_refs=[source_ref],
                first_observed_at=observed_time,
                last_confirmed_at=observed_time,
                reason_codes=["EXPLICIT_FEATURE_STATEMENT"],
            )
            items.append(item)

    return items, revoked_dimensions, explicit_signals


def evaluate_customer_preference_memory(
    db: Optional[Session],
    company_id: str,
    lead_id: Optional[Any],
    current_user_input: str = "",
    recent_messages: Optional[List[Dict[str, Any]]] = None,
    existing_memory_text: Optional[str] = None,
) -> CustomerPreferenceMemorySnapshot:
    """
    Evaluates CustomerPreferenceMemorySnapshot enforcing strict source authority hierarchy.
    ONLY customer-authored text and trusted evidence are used for preferences.
    Assistant responses, system prompt, catalog, or recommendation outputs have ZERO authority.
    """
    lead_id_str = str(lead_id) if lead_id is not None else "0"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Load existing persisted preferences if available in LeadMemory
    existing_items: List[CustomerPreferenceMemoryItem] = []
    if db and lead_id:
        try:
            from database import LeadMemory

            mem_row = db.query(LeadMemory).filter(LeadMemory.lead_id == int(lead_id)).first()
            if mem_row and mem_row.preferences:
                try:
                    parsed_json = json.loads(mem_row.preferences)
                    if isinstance(parsed_json, dict) and "active_preferences" in parsed_json:
                        snap = CustomerPreferenceMemorySnapshot.from_dict(parsed_json)
                        # Load active and temporary items
                        existing_items.extend(snap.active_preferences)
                        existing_items.extend(snap.temporary_preferences)
                except Exception:
                    pass
        except Exception as e:
            log.warning("Could not read LeadMemory for lead_id %s: %s", lead_id, e)

    # Process customer-authored messages ONLY in chronological order (History first, current input last)
    customer_messages: List[Tuple[str, str]] = []  # (text, source_ref)
    if recent_messages:
        for idx, m in enumerate(recent_messages):
            role = m.get("role") or m.get("sender")
            content = m.get("content") or m.get("message")
            if role in ["user", "customer"] and content:
                customer_messages.append((content, f"history_msg_{idx}"))

    if current_user_input and current_user_input.strip():
        curr_strip = current_user_input.strip()
        if not customer_messages or customer_messages[-1][0] != curr_strip:
            customer_messages.append((curr_strip, "current_message"))

    # Extract candidates from customer text
    new_extracted_items: List[CustomerPreferenceMemoryItem] = []
    revoked_dims_set: Set[str] = set()

    for text, ref in customer_messages:
        extracted, rev_dims, _ = extract_preference_candidates_from_text(
            text, company_id, lead_id_str, ref, now_iso
        )
        new_extracted_items.extend(extracted)
        revoked_dims_set.update(rev_dims)

    # Combine existing + new extracted items with Supersession, Revocation, and Staleness logic
    active_items: Dict[str, CustomerPreferenceMemoryItem] = {}
    temporary_items: List[CustomerPreferenceMemoryItem] = []
    inferred_items: List[CustomerPreferenceMemoryItem] = []
    stale_items: List[CustomerPreferenceMemoryItem] = []
    conflicts: List[CustomerPreferenceMemoryItem] = []
    revoked_items: List[CustomerPreferenceMemoryItem] = []

    # Process existing items first
    for item in existing_items:
        dim_str = item.dimension.value if isinstance(item.dimension, Enum) else str(item.dimension)
        if dim_str in revoked_dims_set or "ALL_TEMPORARY" in revoked_dims_set:
            item.status = PreferenceStatus.REVOKED
            revoked_items.append(item)
        elif item.stability == PreferenceStability.CURRENT_CONTEXT_ONLY:
            # Current context items from previous sessions become stale if not re-confirmed in current turn
            item.status = PreferenceStatus.STALE
            stale_items.append(item)
        else:
            active_items[f"{dim_str}:{item.value}"] = item

    # Process new extracted items
    for item in new_extracted_items:
        dim_str = item.dimension.value if isinstance(item.dimension, Enum) else str(item.dimension)
        if dim_str in revoked_dims_set:
            item.status = PreferenceStatus.REVOKED
            revoked_items.append(item)
            continue

        # Check for supersession in same dimension & scope
        for key, existing_item in list(active_items.items()):
            ex_dim = existing_item.dimension.value if isinstance(existing_item.dimension, Enum) else str(existing_item.dimension)
            if ex_dim == dim_str and existing_item.value != item.value:
                # Supersede existing item with new item
                existing_item.status = PreferenceStatus.SUPERSEDED
                existing_item.superseded_by = item.memory_id
                item.supersedes = existing_item.memory_id
                revoked_items.append(existing_item)  # remove from active
                del active_items[key]

        if item.stability == PreferenceStability.CURRENT_CONTEXT_ONLY:
            temporary_items.append(item)
        else:
            active_items[f"{dim_str}:{item.value}"] = item

    active_list = list(active_items.values())

    # Build effective_for_current_context projection:
    # Top priority: temporary preferences for current context, then active stable preferences
    effective_items: List[CustomerPreferenceMemoryItem] = []
    seen_dims: Set[str] = set()

    # 1. Temporary preferences override stable for matching dimension
    for temp in temporary_items:
        t_dim = temp.dimension.value if isinstance(temp.dimension, Enum) else str(temp.dimension)
        effective_items.append(temp)
        seen_dims.add(t_dim)

    # 2. Active stable preferences fill remaining dimensions
    for act in active_list:
        a_dim = act.dimension.value if isinstance(act.dimension, Enum) else str(act.dimension)
        if a_dim not in seen_dims:
            effective_items.append(act)
            seen_dims.add(a_dim)

    snapshot = CustomerPreferenceMemorySnapshot(
        company_id=company_id,
        lead_id=lead_id_str,
        active_preferences=active_list,
        temporary_preferences=temporary_items,
        inferred_hypotheses=inferred_items,
        stale_items=stale_items,
        conflicts=conflicts,
        revoked_items=revoked_items,
        effective_for_current_context=effective_items,
        observed_at=now_iso,
    )

    return snapshot


def evaluate_relationship_context(
    db: Optional[Session],
    company_id: str,
    lead_id: Optional[Any],
    current_user_input: str = "",
    recent_messages: Optional[List[Dict[str, Any]]] = None,
    preference_snapshot: Optional[CustomerPreferenceMemorySnapshot] = None,
) -> RelationshipContextSnapshot:
    """
    Evaluates RelationshipContextSnapshot.
    Continuity status: NEW, RETURNING, REPEAT_BUYER, UNKNOWN.
    REPEAT_BUYER strictly requires authoritative completed order/purchase evidence (SystemEvent or DB Order).
    Prior product discussion != purchase.
    """
    lead_id_str = str(lead_id) if lead_id is not None else "0"
    now_iso = datetime.now(timezone.utc).isoformat()

    continuity = RelationshipContinuity.NEW
    prior_msg_count = 0
    first_seen = None
    last_seen = None
    verified_purchases: List[str] = []
    prior_order_refs: List[str] = []
    prior_discussed_products: List[str] = []
    claimed_prior_purchase = False

    # Check database lead history & system events if db available
    if db and lead_id:
        try:
            from database import Lead, Message, SystemEvent

            lead_row = db.query(Lead).filter(Lead.id == int(lead_id)).first()
            if lead_row:
                if lead_row.conversation_count and lead_row.conversation_count > 1:
                    continuity = RelationshipContinuity.RETURNING
                if lead_row.created_at:
                    first_seen = lead_row.created_at.isoformat()
                if lead_row.updated_at:
                    last_seen = lead_row.updated_at.isoformat()

            # Count total customer messages
            user_phone = str(lead_row.phone) if lead_row and lead_row.phone else None
            if user_phone:
                msg_count = (
                    db.query(Message)
                    .filter(
                        Message.company_id == company_id,
                        Message.user_id == user_phone,
                        Message.sender.in_(["user", "customer"]),
                    )
                    .count()
                )
                if msg_count > 0:
                    prior_msg_count = msg_count
                    if msg_count > 1 and continuity == RelationshipContinuity.NEW:
                        continuity = RelationshipContinuity.RETURNING

            # Check SystemEvents for authoritative completed order events ONLY
            order_events = (
                db.query(SystemEvent)
                .filter(
                    SystemEvent.company_id == company_id,
                    SystemEvent.event_type.in_(
                        ["order_completed", "purchase_completed", "payment_received", "checkout_completed"]
                    ),
                )
                .all()
            )
            for ev in order_events:
                if ev.entity_id == str(lead_id) or (lead_row and ev.entity_id == str(lead_row.phone)):
                    continuity = RelationshipContinuity.REPEAT_BUYER
                    prior_order_refs.append(f"order_event_{ev.id}")
                    if ev.payload:
                        try:
                            p_data = json.loads(ev.payload)
                            if isinstance(p_data, dict) and p_data.get("product_name"):
                                verified_purchases.append(p_data["product_name"])
                        except Exception:
                            pass

        except Exception as e:
            log.warning("Error evaluating relationship context from DB for lead %s: %s", lead_id, e)

    # Check customer messages for claimed purchase or product discussions
    all_texts: List[str] = []
    if current_user_input:
        all_texts.append(current_user_input)
    if recent_messages:
        for m in recent_messages:
            if m.get("role") in ["user", "customer"] and m.get("content"):
                all_texts.append(m["content"])

    full_customer_text = " ".join(all_texts)
    norm_text = _normalize_str(full_customer_text)

    if any(k in norm_text for k in ["اشتريت منكم", "طلبت قبل كده", "اشتريت قبل كده", "bought from you"]):
        claimed_prior_purchase = True

    # Identify discussed products (e.g., Ergo One, Ergo Pro, etc.)
    for prod_keyword in ["ergo one", "ergo pro", "mesh chair", "دفتر", "كرسي"]:
        if prod_keyword in norm_text:
            if prod_keyword not in prior_discussed_products:
                prior_discussed_products.append(prod_keyword)

    active_pref_count = len(preference_snapshot.active_preferences) if preference_snapshot else 0

    return RelationshipContextSnapshot(
        company_id=company_id,
        lead_id=lead_id_str,
        continuity_status=continuity,
        first_customer_interaction_at=first_seen,
        last_customer_interaction_at=last_seen,
        prior_customer_message_count=prior_msg_count,
        claimed_prior_purchase=claimed_prior_purchase,
        verified_prior_purchases=verified_purchases,
        prior_order_refs=prior_order_refs,
        prior_discussed_product_refs=prior_discussed_products,
        active_preference_count=active_pref_count,
        observed_at=now_iso,
    )


def sync_preference_memory_to_db(
    db: Session,
    company_id: str,
    lead_id: int,
    snapshot: CustomerPreferenceMemorySnapshot,
) -> None:
    """
    Persists CustomerPreferenceMemorySnapshot into LeadMemory deterministically and tenant-safely.
    """
    if not db or not lead_id:
        return
    try:
        from database import LeadMemory

        mem_row = db.query(LeadMemory).filter(LeadMemory.lead_id == int(lead_id)).first()
        if not mem_row:
            mem_row = LeadMemory(lead_id=int(lead_id))
            db.add(mem_row)
            db.flush()

        # Update preferences JSON column with canonical snapshot without clobbering communication_profile
        existing_dict = {}
        if mem_row.preferences:
            try:
                parsed = json.loads(mem_row.preferences)
                if isinstance(parsed, dict):
                    existing_dict = parsed
            except Exception:
                existing_dict = {}

        comm_prof = existing_dict.get("communication_profile")
        new_dict = snapshot.to_dict()
        if comm_prof is not None:
            new_dict["communication_profile"] = comm_prof

        mem_row.preferences = json.dumps(new_dict, ensure_ascii=False)
        mem_row.last_updated = datetime.now(timezone.utc)

        # Update legacy fields if appropriate for backward compatibility
        active_color = [p.value for p in snapshot.active_preferences if p.dimension == PreferenceDimension.COLOR]
        active_budget = [p.value for p in snapshot.effective_for_current_context if p.dimension == PreferenceDimension.BUDGET_RANGE]

        if active_budget:
            mem_row.budget = json.dumps({"value": f"{active_budget[0]} EGP", "confidence": 0.9}, ensure_ascii=False)
        if active_color:
            mem_row.product_interest = json.dumps({"value": f"Prefers {active_color[0]}", "confidence": 0.9}, ensure_ascii=False)

        db.commit()
    except Exception as e:
        log.error("Failed to sync preference memory to DB for lead %s: %s", lead_id, e)
        db.rollback()


def format_memory_context_for_prompt(
    preference_snapshot: Optional[CustomerPreferenceMemorySnapshot],
    relationship_snapshot: Optional[RelationshipContextSnapshot],
) -> str:
    """
    Formats bounded, structured memory context for provider system prompt.
    Explicitly separates active preferences, temporary constraints, relationship status,
    and strict rules against fabricating customer claims.
    """
    if not preference_snapshot and not relationship_snapshot:
        return ""

    lines = ["\n[CURRENT CUSTOMER PREFERENCE MEMORY & RELATIONSHIP CONTEXT]"]

    if relationship_snapshot:
        cont_str = relationship_snapshot.continuity_status.value if isinstance(relationship_snapshot.continuity_status, Enum) else str(relationship_snapshot.continuity_status)
        lines.append(f"- Relationship Continuity: {cont_str}")
        if relationship_snapshot.verified_prior_purchases:
            lines.append(f"- Verified Completed Purchases: {', '.join(relationship_snapshot.verified_prior_purchases)}")
        else:
            lines.append("- Verified Completed Purchases: NONE (Do NOT claim customer bought anything previously)")
        if relationship_snapshot.prior_discussed_product_refs:
            lines.append(f"- Previously Discussed Products: {', '.join(relationship_snapshot.prior_discussed_product_refs)}")

    if preference_snapshot:
        active_str_list = []
        for p in preference_snapshot.active_preferences:
            dim_name = p.dimension.value if isinstance(p.dimension, Enum) else str(p.dimension)
            active_str_list.append(f"{dim_name}={p.value} ({p.stability.value})")
        
        temp_str_list = []
        for t in preference_snapshot.temporary_preferences:
            dim_name = t.dimension.value if isinstance(t.dimension, Enum) else str(t.dimension)
            temp_str_list.append(f"{dim_name}={t.value} (Current context constraint)")

        lines.append(f"- Active Stable Preferences: {', '.join(active_str_list) if active_str_list else 'NONE'}")
        lines.append(f"- Current Purchase Constraints: {', '.join(temp_str_list) if temp_str_list else 'NONE'}")
        
        if preference_snapshot.revoked_items:
            lines.append("- Revoked/Deactivated Memories: Color/Budget preferences previously revoked by customer")

    lines.append("MEMORY RULES:")
    lines.append("1. Current customer explicit message ALWAYS overrides historical memory.")
    lines.append("2. Stable preferences are soft context only; do NOT treat them as hard constraints unless requested.")
    lines.append("3. NEVER claim the customer said something ('أنت كنت قلتلي قبل كده') unless verified in Active Preferences.")
    lines.append("4. NEVER claim the customer purchased a product previously unless listed under Verified Completed Purchases.")

    return "\n".join(lines) + "\n"
