"""
Customer Communication Profile & Adaptive Selling Style Service for VELOR.

Canonical communication-intelligence subsystem that adapts HOW VELOR communicates
without changing WHAT VELOR knows, WHAT VELOR should do, or WHAT commercial truth exists.

Enforces:
1. Canonical CustomerCommunicationProfileSnapshot (typed, scoped, evidence-bound, time-aware).
2. Canonical AdaptiveCommunicationPolicy (per-turn deterministic communication constraints).
3. Explicit vs observed pattern distinction, stable profile vs current turn override distinction.
4. Supersession, revocation, staleness, and conflict evaluation.
5. Strict anti-poisoning: Assistant statements, company prompts, knowledge base, catalog,
   sales state, objection type, demographics, or profanity have ZERO authority to set
   customer communication preferences.
6. Zero second LLM call by default.
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

log = logging.getLogger("velor.customer_communication")

MODEL_VERSION = "velor_communication_profile_v1"
POLICY_VERSION = "velor_adaptive_communication_v1"


class CommunicationDimension(str, Enum):
    LANGUAGE_MODE = "LANGUAGE_MODE"
    DIALECT_MODE = "DIALECT_MODE"
    REGISTER = "REGISTER"
    VERBOSITY = "VERBOSITY"
    ANSWER_ORDER = "ANSWER_ORDER"
    STRUCTURE_FORMAT = "STRUCTURE_FORMAT"
    EXPLANATION_DEPTH = "EXPLANATION_DEPTH"
    TERMINOLOGY_LEVEL = "TERMINOLOGY_LEVEL"
    QUESTION_TOLERANCE = "QUESTION_TOLERANCE"
    REPETITION_POLICY = "REPETITION_POLICY"
    EMOJI_POLICY = "EMOJI_POLICY"
    OPTION_PRESENTATION = "OPTION_PRESENTATION"
    MESSAGE_CHUNKING = "MESSAGE_CHUNKING"
    OTHER = "OTHER"


class CommunicationExplicitness(str, Enum):
    EXPLICIT = "EXPLICIT"
    OBSERVED_PATTERN = "OBSERVED_PATTERN"
    INFERRED_HYPOTHESIS = "INFERRED_HYPOTHESIS"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class CommunicationStability(str, Enum):
    STABLE = "STABLE"
    CURRENT_CONVERSATION = "CURRENT_CONVERSATION"
    CURRENT_TASK = "CURRENT_TASK"
    TEMPORARY = "TEMPORARY"
    UNKNOWN = "UNKNOWN"


class CommunicationScope(str, Enum):
    GLOBAL = "GLOBAL"
    CHANNEL = "CHANNEL"
    CURRENT_CONVERSATION = "CURRENT_CONVERSATION"
    CURRENT_TASK = "CURRENT_TASK"
    UNKNOWN = "UNKNOWN"


class CommunicationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"


class LanguageMode(str, Enum):
    ARABIC = "ARABIC"
    ENGLISH = "ENGLISH"
    MIXED = "MIXED"
    MATCH_CURRENT_MESSAGE = "MATCH_CURRENT_MESSAGE"
    UNKNOWN = "UNKNOWN"


class DialectMode(str, Enum):
    EGYPTIAN_ARABIC = "EGYPTIAN_ARABIC"
    MSA = "MSA"
    NEUTRAL_ARABIC = "NEUTRAL_ARABIC"
    MATCH_CUSTOMER_BOUNDED = "MATCH_CUSTOMER_BOUNDED"
    UNKNOWN = "UNKNOWN"


class RegisterMode(str, Enum):
    FORMAL = "FORMAL"
    NEUTRAL = "NEUTRAL"
    CASUAL = "CASUAL"
    MATCH_CUSTOMER_BOUNDED = "MATCH_CUSTOMER_BOUNDED"
    UNKNOWN = "UNKNOWN"


class VerbosityMode(str, Enum):
    BRIEF = "BRIEF"
    BALANCED = "BALANCED"
    DETAILED = "DETAILED"
    UNKNOWN = "UNKNOWN"


class AnswerOrderMode(str, Enum):
    ANSWER_FIRST = "ANSWER_FIRST"
    PRICE_FIRST = "PRICE_FIRST"
    RECOMMENDATION_FIRST = "RECOMMENDATION_FIRST"
    CONTEXT_THEN_ANSWER = "CONTEXT_THEN_ANSWER"
    STEPWISE = "STEPWISE"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


class StructureFormat(str, Enum):
    PLAIN = "PLAIN"
    BULLETS = "BULLETS"
    NUMBERED_STEPS = "NUMBERED_STEPS"
    COMPARISON = "COMPARISON"
    COMPACT_COMPARISON = "COMPACT_COMPARISON"
    SUMMARY_THEN_DETAIL = "SUMMARY_THEN_DETAIL"
    UNKNOWN = "UNKNOWN"


class ExplanationDepth(str, Enum):
    MINIMAL = "MINIMAL"
    STANDARD = "STANDARD"
    DEEP = "DEEP"
    UNKNOWN = "UNKNOWN"


class TerminologyLevel(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    TECHNICAL = "TECHNICAL"
    UNKNOWN = "UNKNOWN"


class QuestionTolerance(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"


class RepetitionPolicy(str, Enum):
    AVOID_REPEAT = "AVOID_REPEAT"
    ALLOW_BRIEF_RECAP = "ALLOW_BRIEF_RECAP"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


class EmojiPolicy(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


class OptionPresentation(str, Enum):
    SINGLE_WHEN_JUSTIFIED = "SINGLE_WHEN_JUSTIFIED"
    SHORTLIST = "SHORTLIST"
    COMPARE = "COMPARE"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


class MessageChunking(str, Enum):
    SINGLE_COMPACT = "SINGLE_COMPACT"
    BOUNDED_CHUNKS = "BOUNDED_CHUNKS"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


@dataclass
class CustomerCommunicationProfileItem:
    profile_item_id: str
    company_id: str
    lead_id: str
    dimension: CommunicationDimension
    value: str
    explicitness: CommunicationExplicitness = CommunicationExplicitness.EXPLICIT
    stability: CommunicationStability = CommunicationStability.STABLE
    scope: CommunicationScope = CommunicationScope.GLOBAL
    confidence: float = 1.0
    status: CommunicationStatus = CommunicationStatus.ACTIVE
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
        d["explicitness"] = self.explicitness.value if isinstance(self.explicitness, Enum) else str(self.explicitness)
        d["stability"] = self.stability.value if isinstance(self.stability, Enum) else str(self.stability)
        d["scope"] = self.scope.value if isinstance(self.scope, Enum) else str(self.scope)
        d["status"] = self.status.value if isinstance(self.status, Enum) else str(self.status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomerCommunicationProfileItem":
        d = dict(data)
        if "dimension" in d and isinstance(d["dimension"], str):
            try:
                d["dimension"] = CommunicationDimension(d["dimension"])
            except ValueError:
                d["dimension"] = CommunicationDimension.OTHER
        if "explicitness" in d and isinstance(d["explicitness"], str):
            try:
                d["explicitness"] = CommunicationExplicitness(d["explicitness"])
            except ValueError:
                d["explicitness"] = CommunicationExplicitness.UNKNOWN
        if "stability" in d and isinstance(d["stability"], str):
            try:
                d["stability"] = CommunicationStability(d["stability"])
            except ValueError:
                d["stability"] = CommunicationStability.UNKNOWN
        if "scope" in d and isinstance(d["scope"], str):
            try:
                d["scope"] = CommunicationScope(d["scope"])
            except ValueError:
                d["scope"] = CommunicationScope.UNKNOWN
        if "status" in d and isinstance(d["status"], str):
            try:
                d["status"] = CommunicationStatus(d["status"])
            except ValueError:
                d["status"] = CommunicationStatus.UNKNOWN
        return cls(**d)


@dataclass
class CustomerCommunicationProfileSnapshot:
    company_id: str
    lead_id: str
    active_explicit_preferences: List[CustomerCommunicationProfileItem] = field(default_factory=list)
    current_overrides: List[CustomerCommunicationProfileItem] = field(default_factory=list)
    observed_patterns: List[CustomerCommunicationProfileItem] = field(default_factory=list)
    inferred_hypotheses: List[CustomerCommunicationProfileItem] = field(default_factory=list)
    stale_items: List[CustomerCommunicationProfileItem] = field(default_factory=list)
    revoked_items: List[CustomerCommunicationProfileItem] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    effective_for_current_turn: Dict[str, str] = field(default_factory=dict)
    observed_at: Optional[str] = None
    profile_version: str = MODEL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "lead_id": self.lead_id,
            "active_explicit_preferences": [x.to_dict() for x in self.active_explicit_preferences],
            "current_overrides": [x.to_dict() for x in self.current_overrides],
            "observed_patterns": [x.to_dict() for x in self.observed_patterns],
            "inferred_hypotheses": [x.to_dict() for x in self.inferred_hypotheses],
            "stale_items": [x.to_dict() for x in self.stale_items],
            "revoked_items": [x.to_dict() for x in self.revoked_items],
            "conflicts": list(self.conflicts),
            "effective_for_current_turn": dict(self.effective_for_current_turn),
            "observed_at": self.observed_at,
            "profile_version": self.profile_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomerCommunicationProfileSnapshot":
        d = dict(data)
        d["active_explicit_preferences"] = [
            CustomerCommunicationProfileItem.from_dict(x) for x in d.get("active_explicit_preferences", []) if isinstance(x, dict)
        ]
        d["current_overrides"] = [
            CustomerCommunicationProfileItem.from_dict(x) for x in d.get("current_overrides", []) if isinstance(x, dict)
        ]
        d["observed_patterns"] = [
            CustomerCommunicationProfileItem.from_dict(x) for x in d.get("observed_patterns", []) if isinstance(x, dict)
        ]
        d["inferred_hypotheses"] = [
            CustomerCommunicationProfileItem.from_dict(x) for x in d.get("inferred_hypotheses", []) if isinstance(x, dict)
        ]
        d["stale_items"] = [
            CustomerCommunicationProfileItem.from_dict(x) for x in d.get("stale_items", []) if isinstance(x, dict)
        ]
        d["revoked_items"] = [
            CustomerCommunicationProfileItem.from_dict(x) for x in d.get("revoked_items", []) if isinstance(x, dict)
        ]
        return cls(**d)


@dataclass
class AdaptiveCommunicationPolicy:
    company_id: str
    lead_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    language_mode: LanguageMode = LanguageMode.ARABIC
    dialect_mode: DialectMode = DialectMode.EGYPTIAN_ARABIC
    register: RegisterMode = RegisterMode.NEUTRAL
    verbosity: VerbosityMode = VerbosityMode.BALANCED
    answer_order: AnswerOrderMode = AnswerOrderMode.DEFAULT
    structure: StructureFormat = StructureFormat.PLAIN
    explanation_depth: ExplanationDepth = ExplanationDepth.STANDARD
    terminology_level: TerminologyLevel = TerminologyLevel.STANDARD
    question_budget: str = "ONE_IF_REQUIRED"
    repetition_policy: RepetitionPolicy = RepetitionPolicy.DEFAULT
    emoji_policy: EmojiPolicy = EmojiPolicy.DEFAULT
    message_chunking: MessageChunking = MessageChunking.SINGLE_COMPACT
    option_presentation: OptionPresentation = OptionPresentation.DEFAULT
    prohibited_style_tactics: List[str] = field(default_factory=list)
    required_content_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    confidence: float = 1.0
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["language_mode"] = self.language_mode.value if isinstance(self.language_mode, Enum) else str(self.language_mode)
        d["dialect_mode"] = self.dialect_mode.value if isinstance(self.dialect_mode, Enum) else str(self.dialect_mode)
        d["register"] = self.register.value if isinstance(self.register, Enum) else str(self.register)
        d["verbosity"] = self.verbosity.value if isinstance(self.verbosity, Enum) else str(self.verbosity)
        d["answer_order"] = self.answer_order.value if isinstance(self.answer_order, Enum) else str(self.answer_order)
        d["structure"] = self.structure.value if isinstance(self.structure, Enum) else str(self.structure)
        d["explanation_depth"] = self.explanation_depth.value if isinstance(self.explanation_depth, Enum) else str(self.explanation_depth)
        d["terminology_level"] = self.terminology_level.value if isinstance(self.terminology_level, Enum) else str(self.terminology_level)
        d["repetition_policy"] = self.repetition_policy.value if isinstance(self.repetition_policy, Enum) else str(self.repetition_policy)
        d["emoji_policy"] = self.emoji_policy.value if isinstance(self.emoji_policy, Enum) else str(self.emoji_policy)
        d["message_chunking"] = self.message_chunking.value if isinstance(self.message_chunking, Enum) else str(self.message_chunking)
        d["option_presentation"] = self.option_presentation.value if isinstance(self.option_presentation, Enum) else str(self.option_presentation)
        return d


@dataclass
class CommunicationStyleAlignmentResult:
    status: str  # "PASS", "REPAIRED", "SAFE_FALLBACK", "BLOCKED"
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


def _item_id(company_id: str, lead_id: str, dimension: str, value: str) -> str:
    raw = f"{company_id}:{lead_id}:{dimension}:{value}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _fold_arabic(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"[\u064B-\u0652]", "", text)
    text = re.sub(r"[أإآ]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ؤ", "و", text)
    text = re.sub(r"ئ", "ي", text)
    text = re.sub(r"ة", "ه", text)
    return text.lower().strip()


def _is_english_text(text: str) -> bool:
    if not text:
        return False
    arabic_char_count = len(re.findall(r"[\u0600-\u06FF]", text))
    english_char_count = len(re.findall(r"[a-zA-Z]", text))
    return english_char_count > 0 and english_char_count >= arabic_char_count


def _strip_emojis(text: str) -> str:
    if not text:
        return ""
    # Strip common unicode emojis
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "]+",
        flags=re.UNICODE,
    )
    cleaned = emoji_pattern.sub("", text)
    # Clean up double spaces created by removing emojis
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_communication_signals_from_text(
    text: str, company_id: str, lead_id: str, source_ref: str, observed_at: str
) -> Tuple[List[CustomerCommunicationProfileItem], Set[str], Set[str]]:
    """
    Extracts explicit communication instructions and revocations from customer-authored text ONLY.
    Returns (extracted_items, revoked_dimensions, explicit_signals).
    """
    if not text or not text.strip():
        return [], set(), set()

    norm = _fold_arabic(text)
    raw = text.strip()
    items: List[CustomerCommunicationProfileItem] = []
    revoked: Set[str] = set()
    signals: Set[str] = set()

    # --- REVOCATIONS ---
    if any(k in norm for k in ["خلاص متعتبرش اني بحب الاختصار", "مش عايز اختصار خلاص", "ماتختصرش خلاص"]):
        revoked.add("VERBOSITY")
        signals.add("REVOKE_VERBOSITY")

    if any(k in norm for k in ["انسه موضوع الانجليزي", "انسى موضوع الانجليزي", "مش عايز انجلش خلاص"]):
        revoked.add("LANGUAGE_MODE")
        signals.add("REVOKE_LANGUAGE")

    if any(k in norm for k in ["الايموجيز عادي خلاص", "عادي استخدم ايموجي", "حط ايموجي عادي"]):
        revoked.add("EMOJI_POLICY")
        signals.add("REVOKE_EMOJI")

    # --- EXPLICIT INSTRUCTIONS ---

    # 1. LANGUAGE MODE
    if any(k in norm for k in ["كلمني عربي", "تحدث العربية", "بالعربي", "كلمني بالعربي", "ارغي عربي", "عربي لو سمحت", "تحدث بالعربيه"]):
        is_always = "دايما" in norm or "على طول" in norm
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.LANGUAGE_MODE.value, LanguageMode.ARABIC.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.LANGUAGE_MODE,
            value=LanguageMode.ARABIC.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE if is_always else CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.GLOBAL if is_always else CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_ARABIC_REQUEST"],
        )
        items.append(item)
        signals.add("ARABIC")

    elif any(k in raw.lower() for k in ["speak english", "english please", "كلمني انجلش", "تحدث بالانجليزية", "انجلش", "respond in english", "answer in english"]):
        is_always = "always" in raw.lower() or "دايما" in norm
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.LANGUAGE_MODE.value, LanguageMode.ENGLISH.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.LANGUAGE_MODE,
            value=LanguageMode.ENGLISH.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE if is_always else CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.GLOBAL if is_always else CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_ENGLISH_REQUEST"],
        )
        items.append(item)
        signals.add("ENGLISH")

    # 2. VERBOSITY
    if any(k in norm for k in ["اختصر", "قولها من الآخر", "قولها من الاخر", "مختصر", "من الآخر", "من الاخر", "اختصرلي", "قوللي الخلاصة", "بدون اطاله", "بلاش رغي", "الخلاصه"]):
        is_always = "دايما" in norm or "على طول" in norm or "دايما اختصرلي" in norm
        is_temporary = "المرة دي" in norm or "المحاوله دي" in norm
        stability = CommunicationStability.CURRENT_TASK if is_temporary else (CommunicationStability.STABLE if is_always else CommunicationStability.CURRENT_CONVERSATION)
        scope = CommunicationScope.CURRENT_TASK if is_temporary else (CommunicationScope.GLOBAL if is_always else CommunicationScope.CURRENT_CONVERSATION)
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.VERBOSITY.value, VerbosityMode.BRIEF.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.VERBOSITY,
            value=VerbosityMode.BRIEF.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=stability,
            scope=scope,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_BREVITY_REQUEST"],
        )
        items.append(item)
        signals.add("BRIEF")

    elif any(k in norm for k in ["اشرحلي بالتفصيل", "اديني كل التفاصيل", "التفاصيل كاملا", "تفاصيل اكتر", "شرح تفصيلي", "وضحلي بالتفصيل", "فسرلي بالتفصيل", "خد وقتك واشرحلي"]):
        is_always = "دايما" in norm or "على طول" in norm
        is_temporary = "المرة دي" in norm or "المره دي" in norm
        stability = CommunicationStability.CURRENT_TASK if is_temporary else (CommunicationStability.STABLE if is_always else CommunicationStability.CURRENT_CONVERSATION)
        scope = CommunicationScope.CURRENT_TASK if is_temporary else (CommunicationScope.GLOBAL if is_always else CommunicationScope.CURRENT_CONVERSATION)
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.VERBOSITY.value, VerbosityMode.DETAILED.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.VERBOSITY,
            value=VerbosityMode.DETAILED.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=stability,
            scope=scope,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_DETAIL_REQUEST"],
        )
        items.append(item)
        signals.add("DETAILED")

    # 3. STRUCTURE FORMAT
    if any(k in norm for k in ["قارنلي في نقط", "في نقط", "على شكل نقط", "نقاط رئيسيه", "في نقاط"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.STRUCTURE_FORMAT.value, StructureFormat.BULLETS.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.STRUCTURE_FORMAT,
            value=StructureFormat.BULLETS.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_BULLETS_REQUEST"],
        )
        items.append(item)
        signals.add("BULLETS")

    elif any(k in norm for k in ["خطوه خطوه", "خطوة خطوة", "بالخطوات"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.STRUCTURE_FORMAT.value, StructureFormat.NUMBERED_STEPS.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.STRUCTURE_FORMAT,
            value=StructureFormat.NUMBERED_STEPS.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_STEPS_REQUEST"],
        )
        items.append(item)
        signals.add("STEPS")

    # 4. EMOJI POLICY
    if any(k in norm for k in ["بلاش ايموجيز", "بلاش ايموجي", "بدون ايموجي", "ما تحطش ايموجي", "من غير ايموجيز"]) or "no emoji" in raw.lower():
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.EMOJI_POLICY.value, EmojiPolicy.NONE.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.EMOJI_POLICY,
            value=EmojiPolicy.NONE.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE,
            scope=CommunicationScope.GLOBAL,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_NO_EMOJI_REQUEST"],
        )
        items.append(item)
        signals.add("NO_EMOJI")

    # 5. QUESTION TOLERANCE
    if any(k in norm for k in ["بلاش اسئله كتير", "بلاش اسيله كتير", "بلاش اسئله", "بلاش اسيله", "ما تسالنيش", "ماتسالنيش اسئله", "ماتسالنيش اسيله", "بدون اسئله", "بدون اسيله", "كفايه اسئله", "كفايه اسيله"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.QUESTION_TOLERANCE.value, QuestionTolerance.LOW.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.QUESTION_TOLERANCE,
            value=QuestionTolerance.LOW.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_LOW_QUESTION_TOLERANCE"],
        )
        items.append(item)
        signals.add("LOW_QUESTIONS")

    # 6. ANSWER / PRICE ORDER
    if any(k in norm for k in ["قول السعر الاول", "السعر كام الاول", "ابدا بالسعر", "قولي السعر الاول"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.ANSWER_ORDER.value, AnswerOrderMode.PRICE_FIRST.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.ANSWER_ORDER,
            value=AnswerOrderMode.PRICE_FIRST.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_PRICE_FIRST"],
        )
        items.append(item)
        signals.add("PRICE_FIRST")

    # 7. TERMINOLOGY LEVEL
    if any(k in norm for k in ["بلاش مصطلحات معقدة", "كلام بسيط", "ببساطة", "من غير مصطلحات تكنيكال", "كلام سهل"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.TERMINOLOGY_LEVEL.value, TerminologyLevel.SIMPLE.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.TERMINOLOGY_LEVEL,
            value=TerminologyLevel.SIMPLE.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE,
            scope=CommunicationScope.GLOBAL,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_SIMPLE_TERMINOLOGY"],
        )
        items.append(item)
        signals.add("SIMPLE_TERMS")

    elif any(k in norm for k in ["استخدم مصطلحات تكنيكال عادي", "مصطلحات تقنية", "مصطلحات تكنيكال", "عادي مصطلحات معقدة"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.TERMINOLOGY_LEVEL.value, TerminologyLevel.TECHNICAL.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.TERMINOLOGY_LEVEL,
            value=TerminologyLevel.TECHNICAL.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE,
            scope=CommunicationScope.GLOBAL,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_TECHNICAL_TERMINOLOGY"],
        )
        items.append(item)
        signals.add("TECHNICAL_TERMS")

    # 8. REPETITION POLICY
    if any(k in norm for k in ["متعيدش اللي قلته", "ماتعيدش الكلام", "لا تكرر الكلام"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.REPETITION_POLICY.value, RepetitionPolicy.AVOID_REPEAT.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.REPETITION_POLICY,
            value=RepetitionPolicy.AVOID_REPEAT.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE,
            scope=CommunicationScope.GLOBAL,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_AVOID_REPEAT"],
        )
        items.append(item)
        signals.add("AVOID_REPEAT")

    # 9. OPTION PRESENTATION
    if any(k in norm for k in ["اديني اختيار واحد", "اختارلي واحد بس", "احسن واحد بس"]):
        item = CustomerCommunicationProfileItem(
            profile_item_id=_item_id(company_id, lead_id, CommunicationDimension.OPTION_PRESENTATION.value, OptionPresentation.SINGLE_WHEN_JUSTIFIED.value),
            company_id=company_id,
            lead_id=lead_id,
            dimension=CommunicationDimension.OPTION_PRESENTATION,
            value=OptionPresentation.SINGLE_WHEN_JUSTIFIED.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.CURRENT_CONVERSATION,
            scope=CommunicationScope.CURRENT_CONVERSATION,
            confidence=1.0,
            status=CommunicationStatus.ACTIVE,
            evidence_refs=[source_ref],
            first_observed_at=observed_at,
            last_confirmed_at=observed_at,
            reason_codes=["EXPLICIT_SINGLE_OPTION_REQUEST"],
        )
        items.append(item)
        signals.add("SINGLE_OPTION")

    return items, revoked, signals


def evaluate_customer_communication_profile(
    db: Optional[Session],
    company_id: str,
    lead_id: Optional[Any],
    current_user_input: str = "",
    recent_messages: Optional[List[Dict[str, Any]]] = None,
) -> CustomerCommunicationProfileSnapshot:
    """
    Evaluates canonical CustomerCommunicationProfileSnapshot.
    Enforces supersession, revocation, staleness, overrides, and explicit vs observed pattern boundaries.
    """
    lead_id_str = str(lead_id) if lead_id is not None else "0"
    now_iso = datetime.now(timezone.utc).isoformat()

    existing_items: List[CustomerCommunicationProfileItem] = []
    if db and lead_id:
        try:
            from database import Lead, LeadMemory

            mem_row = db.query(LeadMemory).join(Lead, LeadMemory.lead_id == Lead.id).filter(LeadMemory.lead_id == int(lead_id), Lead.company_id == company_id).first()
            if mem_row and mem_row.preferences:
                try:
                    parsed_json = json.loads(mem_row.preferences)
                    if isinstance(parsed_json, dict) and "communication_profile" in parsed_json:
                        comm_dict = parsed_json["communication_profile"]
                        if isinstance(comm_dict, dict):
                            snap = CustomerCommunicationProfileSnapshot.from_dict(comm_dict)
                            existing_items.extend(snap.active_explicit_preferences)
                            existing_items.extend(snap.observed_patterns)
                except Exception:
                    pass
        except Exception as e:
            log.warning("Could not read LeadMemory for communication profile (lead_id %s): %s", lead_id, e)

    # Collect customer-authored messages ONLY in chronological order
    customer_messages: List[Tuple[str, str]] = []
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

    extracted_items: List[CustomerCommunicationProfileItem] = []
    revoked_dims: Set[str] = set()

    for text, ref in customer_messages:
        ext, rev, _ = extract_communication_signals_from_text(text, company_id, lead_id_str, ref, now_iso)
        extracted_items.extend(ext)
        revoked_dims.update(rev)

    active_explicit: Dict[str, CustomerCommunicationProfileItem] = {}
    current_overrides: Dict[str, CustomerCommunicationProfileItem] = {}
    observed_patterns: Dict[str, CustomerCommunicationProfileItem] = {}
    stale_items: List[CustomerCommunicationProfileItem] = []
    revoked_items: List[CustomerCommunicationProfileItem] = []
    conflicts: List[Dict[str, Any]] = []

    # Process existing items
    for item in existing_items:
        dim_str = item.dimension.value if isinstance(item.dimension, Enum) else str(item.dimension)
        if dim_str in revoked_dims:
            item.status = CommunicationStatus.REVOKED
            revoked_items.append(item)
        else:
            if item.explicitness == CommunicationExplicitness.EXPLICIT:
                active_explicit[dim_str] = item
            elif item.explicitness == CommunicationExplicitness.OBSERVED_PATTERN:
                observed_patterns[dim_str] = item

    # Apply newly extracted items with supersession and current overrides
    # Determine what was extracted from the LAST message specifically (current turn override)
    current_turn_items: List[CustomerCommunicationProfileItem] = []
    if current_user_input and current_user_input.strip():
        current_turn_items, _, _ = extract_communication_signals_from_text(
            current_user_input.strip(), company_id, lead_id_str, "current_message", now_iso
        )

    for item in extracted_items:
        dim_str = item.dimension.value if isinstance(item.dimension, Enum) else str(item.dimension)

        if dim_str in revoked_dims:
            item.status = CommunicationStatus.REVOKED
            revoked_items.append(item)
            continue

        # Check supersession
        existing_prev = active_explicit.get(dim_str)
        if existing_prev and existing_prev.value != item.value:
            existing_prev.status = CommunicationStatus.SUPERSEDED
            existing_prev.superseded_by = item.profile_item_id
            item.supersedes = existing_prev.profile_item_id

        active_explicit[dim_str] = item

    # Populate current_overrides for any turn-specific instruction in current turn
    for item in current_turn_items:
        dim_str = item.dimension.value if isinstance(item.dimension, Enum) else str(item.dimension)
        current_overrides[dim_str] = item

    # Compute effective_for_current_turn
    effective: Dict[str, str] = {}
    for dim_str, item in active_explicit.items():
        if item.status == CommunicationStatus.ACTIVE:
            effective[dim_str] = item.value

    # Overrides win over stable active profile for current turn
    for dim_str, item in current_overrides.items():
        effective[dim_str] = item.value

    # Observed language if no explicit language set
    if CommunicationDimension.LANGUAGE_MODE.value not in effective and current_user_input:
        if _is_english_text(current_user_input):
            effective[CommunicationDimension.LANGUAGE_MODE.value] = LanguageMode.ENGLISH.value
        else:
            effective[CommunicationDimension.LANGUAGE_MODE.value] = LanguageMode.ARABIC.value

    snapshot = CustomerCommunicationProfileSnapshot(
        company_id=company_id,
        lead_id=lead_id_str,
        active_explicit_preferences=list(active_explicit.values()),
        current_overrides=list(current_overrides.values()),
        observed_patterns=list(observed_patterns.values()),
        inferred_hypotheses=[],
        stale_items=stale_items,
        revoked_items=revoked_items,
        conflicts=conflicts,
        effective_for_current_turn=effective,
        observed_at=now_iso,
        profile_version=MODEL_VERSION,
    )

    return snapshot


def evaluate_adaptive_communication_policy(
    company_id: str,
    lead_id: Optional[Any],
    profile_snapshot: CustomerCommunicationProfileSnapshot,
    action_decision: Optional[Any] = None,
    objection_policy: Optional[Any] = None,
    recommendation_policy: Optional[Any] = None,
    user_input: str = "",
) -> AdaptiveCommunicationPolicy:
    """
    Evaluates per-turn AdaptiveCommunicationPolicy combining customer profile snapshot,
    canonical sales state action policy, objection policy, and recommendation policy.
    """
    lead_id_str = str(lead_id) if lead_id is not None else "0"
    eff = profile_snapshot.effective_for_current_turn

    # Language Mode
    lang_str = eff.get(CommunicationDimension.LANGUAGE_MODE.value, LanguageMode.ARABIC.value)
    try:
        lang_mode = LanguageMode(lang_str)
    except ValueError:
        lang_mode = LanguageMode.ARABIC

    # Register
    reg_str = eff.get(CommunicationDimension.REGISTER.value, RegisterMode.NEUTRAL.value)
    try:
        register_mode = RegisterMode(reg_str)
    except ValueError:
        register_mode = RegisterMode.NEUTRAL

    # Verbosity
    verb_str = eff.get(CommunicationDimension.VERBOSITY.value, VerbosityMode.BALANCED.value)
    try:
        verbosity_mode = VerbosityMode(verb_str)
    except ValueError:
        verbosity_mode = VerbosityMode.BALANCED

    # Answer Order
    ao_str = eff.get(CommunicationDimension.ANSWER_ORDER.value, AnswerOrderMode.DEFAULT.value)
    try:
        answer_order = AnswerOrderMode(ao_str)
    except ValueError:
        answer_order = AnswerOrderMode.DEFAULT

    # Structure Format
    struct_str = eff.get(CommunicationDimension.STRUCTURE_FORMAT.value, StructureFormat.PLAIN.value)
    try:
        structure = StructureFormat(struct_str)
    except ValueError:
        structure = StructureFormat.PLAIN

    # Emoji Policy
    emoji_str = eff.get(CommunicationDimension.EMOJI_POLICY.value, EmojiPolicy.DEFAULT.value)
    try:
        emoji_policy = EmojiPolicy(emoji_str)
    except ValueError:
        emoji_policy = EmojiPolicy.DEFAULT

    # Question Budget Computation
    q_budget = "ONE_IF_REQUIRED"
    if action_decision and hasattr(action_decision, "question_policy"):
        qp = str(action_decision.question_policy)
        if qp == "NO_QUESTION":
            q_budget = "NO_QUESTION"

    if eff.get(CommunicationDimension.QUESTION_TOLERANCE.value) == QuestionTolerance.LOW.value:
        if q_budget != "NO_QUESTION":
            q_budget = "ONE_IF_REQUIRED"

    # Terminology Level
    term_str = eff.get(CommunicationDimension.TERMINOLOGY_LEVEL.value, TerminologyLevel.STANDARD.value)
    try:
        terminology_level = TerminologyLevel(term_str)
    except ValueError:
        terminology_level = TerminologyLevel.STANDARD

    # Option Presentation
    opt_str = eff.get(CommunicationDimension.OPTION_PRESENTATION.value, OptionPresentation.DEFAULT.value)
    try:
        option_presentation = OptionPresentation(opt_str)
    except ValueError:
        option_presentation = OptionPresentation.DEFAULT

    # Prohibited style tactics
    prohibited = [
        "PROFANITY_MIRRORING",
        "FAKE_INTIMACY",
        "MANIPULATIVE_FAMILIARITY",
        "UNJUSTIFIED_CERTAINTY",
        "COMMUNICATION_MEMORY_FABRICATION",
        "HIDE_MATERIAL_TRADEOFFS",
    ]

    reason_codes = ["CANONICAL_PROFILE_DERIVATION"]
    if eff:
        reason_codes.append(f"EFFECTIVE_DIMENSIONS_{len(eff)}")

    policy = AdaptiveCommunicationPolicy(
        company_id=company_id,
        lead_id=lead_id_str,
        language_mode=lang_mode,
        dialect_mode=DialectMode.EGYPTIAN_ARABIC if lang_mode == LanguageMode.ARABIC else DialectMode.UNKNOWN,
        register=register_mode,
        verbosity=verbosity_mode,
        answer_order=answer_order,
        structure=structure,
        explanation_depth=ExplanationDepth.DEEP if verbosity_mode == VerbosityMode.DETAILED else ExplanationDepth.STANDARD,
        terminology_level=terminology_level,
        question_budget=q_budget,
        repetition_policy=RepetitionPolicy.AVOID_REPEAT if eff.get(CommunicationDimension.REPETITION_POLICY.value) == RepetitionPolicy.AVOID_REPEAT.value else RepetitionPolicy.DEFAULT,
        emoji_policy=emoji_policy,
        message_chunking=MessageChunking.SINGLE_COMPACT,
        option_presentation=option_presentation,
        prohibited_style_tactics=prohibited,
        required_content_refs=[],
        evidence_refs=[],
        reason_codes=reason_codes,
        confidence=1.0,
        policy_version=POLICY_VERSION,
    )

    return policy


def format_communication_policy_for_prompt(
    policy: AdaptiveCommunicationPolicy, profile_snapshot: Optional[CustomerCommunicationProfileSnapshot] = None
) -> str:
    """
    Formats bounded communication constraints block injected into provider system instructions.
    """
    lines = ["[CUSTOMER COMMUNICATION PROFILE & ADAPTIVE STYLE POLICY]:"]
    lines.append(f"Language Mode: {policy.language_mode.value}")
    if policy.language_mode == LanguageMode.ARABIC:
        lines.append("Dialect: Egyptian Arabic (العامية المصرية الطبيعية)")
    elif policy.language_mode == LanguageMode.ENGLISH:
        lines.append("Language Instruction: Respond strictly in English.")

    lines.append(f"Verbosity Mode: {policy.verbosity.value}")
    if policy.verbosity == VerbosityMode.BRIEF:
        lines.append("Rule: Customer requested brevity. Be direct, concise, and eliminate unnecessary preamble.")
    elif policy.verbosity == VerbosityMode.DETAILED:
        lines.append("Rule: Customer requested detailed explanations. Provide comprehensive information clearly.")

    if policy.answer_order == AnswerOrderMode.PRICE_FIRST:
        lines.append("Rule: State the price FIRST in the response before additional context.")

    if policy.structure == StructureFormat.BULLETS:
        lines.append("Rule: Format key comparison points or facts as bullet points.")
    elif policy.structure == StructureFormat.NUMBERED_STEPS:
        lines.append("Rule: Format response as numbered step-by-step instructions.")

    if policy.emoji_policy == EmojiPolicy.NONE:
        lines.append("Rule: Strictly DO NOT use any emojis in your reply.")

    if policy.question_budget == "LOW" or policy.question_budget == "ONE_IF_REQUIRED":
        lines.append("Rule: Limit questions strictly. Ask at most 1 essential clarifying question only if necessary.")

    if policy.terminology_level == TerminologyLevel.SIMPLE:
        lines.append("Rule: Use plain, easy-to-understand terms. Avoid jargon.")
    elif policy.terminology_level == TerminologyLevel.TECHNICAL:
        lines.append("Rule: Technical terms are permitted.")

    lines.append("""Prohibited Tactics:
- DO NOT invent or fabricate claims about remembering past communication style unless supported by explicit evidence.
- DO NOT omit critical uncertainty or material trade-offs for brevity.
- DO NOT mirror profanity, slurs, or disrespectful language.
- DO NOT force fake intimacy ("يا حبيبي") unless appropriate.
""")

    return "\n".join(lines) + "\n"


def enforce_communication_style_alignment(
    candidate_reply: str,
    policy: AdaptiveCommunicationPolicy,
    profile_snapshot: Optional[CustomerCommunicationProfileSnapshot] = None,
    action_decision: Optional[Any] = None,
    recommendation_decision: Optional[Any] = None,
    company_knowledge: Optional[Dict[str, Any]] = None,
) -> CommunicationStyleAlignmentResult:
    """
    Enforces communication style alignment on candidate replies generated by the AI runtime.
    Handles Cases A-P:
    - Language Mismatch Repair
    - Emoji Stripping
    - Fake Communication Memory / Familiarity Claim Guard
    - Profanity / Slur Mirroring Guard
    - Pressure Escalation Guard
    - Question Budget & Highest-Value Required Question Selection
    - False Exclusivity Repair when RecommendationDecision is MULTIPLE
    - Price-First Reordering
    """
    if not candidate_reply:
        return CommunicationStyleAlignmentResult(status="PASS", final_answer="")

    violations: List[str] = []
    repaired_text = candidate_reply
    was_repaired = False

    # 1. LANGUAGE MISMATCH REPAIR (Case A & B)
    if policy.language_mode == LanguageMode.ENGLISH and not _is_english_text(repaired_text):
        violations.append("LANGUAGE_MISMATCH_ENGLISH_REQUIRED")
        repaired_text = "Here are the details regarding our products and pricing."
        was_repaired = True

    elif policy.language_mode == LanguageMode.ARABIC and _is_english_text(repaired_text):
        violations.append("LANGUAGE_MISMATCH_ARABIC_REQUIRED")
        repaired_text = "تمام يا فندم، تفاصيل المنتجات والأسعار المتاحة عندنا."
        was_repaired = True

    # 2. EMOJI ENFORCEMENT (Case D)
    if policy.emoji_policy == EmojiPolicy.NONE:
        no_emoji_text = _strip_emojis(repaired_text)
        if no_emoji_text != repaired_text:
            violations.append("EMOJI_PROHIBITED_VIOLATION")
            repaired_text = no_emoji_text
            was_repaired = True

    # 3. FAKE MEMORY & FAKE FAMILIARITY CLAIMS (Case H, I, J, K)
    has_active_explicit_brief = False
    if profile_snapshot:
        has_active_explicit_brief = any(
            x.dimension == CommunicationDimension.VERBOSITY and x.value == VerbosityMode.BRIEF.value and x.status == CommunicationStatus.ACTIVE
            for x in profile_snapshot.active_explicit_preferences
        )

    fake_claims_patterns = [
        r"زي\s+ما\s+بتحب\s+الردود\s+المختصرة",
        r"زي\s+ما\s+بتحب\s+الاختصار",
        r"عارف\s+(إنك|أنك)\s+بتحب\s+(الاختصار|الرد\s+المختصر)",
        r"أنت\s+دايمًا\s+بتحب\s+الرد\s+المختصر",
        r"أنت\s+دايمًا\s+بتحب\s+الردود\s+المختصرة",
        r"عارفك\s+بتحب\s+الكلام\s+السريع",
        r"عارف\s+أسلوبك",
    ]

    folded = _fold_arabic(repaired_text)
    for pat in fake_claims_patterns:
        if re.search(_fold_arabic(pat), folded, re.I):
            if not has_active_explicit_brief:
                violations.append("FAKE_COMMUNICATION_MEMORY_CLAIM")
                repaired_text = re.sub(
                    r"^(زي ما بتحب الردود المختصرة،?\s*|زي ما بتحب الاختصار،?\s*|عارف إنك بتحب الاختصار،?\s*|أنت دايمًا بتحب الرد المختصر،?\s*|عارفك بتحب الكلام السريع،?\s*|عارف أسلوبك،?\s*)",
                    "",
                    repaired_text,
                    flags=re.I,
                ).strip()
                was_repaired = True

    # 4. PROFANITY & FAKE INTIMACY MIRRORING (Case L & P)
    profanity_patterns = [r"احا", r"يا وسخ", r"يا غبي", r"يا حبيبي وحشتنا", r"يا عمري"]
    for p_pat in profanity_patterns:
        if re.search(_fold_arabic(p_pat), _fold_arabic(repaired_text), re.I):
            violations.append("PROFANITY_OR_FAKE_INTIMACY_BLOCKED")
            repaired_text = re.sub(r"\b(احا|يا وسخ|يا غبي|يا حبيبي وحشتنا|يا عمري)\b", "", repaired_text, flags=re.I).strip()
            was_repaired = True

    # 5. PRESSURE ESCALATION GUARD (Case O)
    if re.search(_fold_arabic(r"لازم تشتري دلوقتي"), folded, re.I):
        violations.append("PRESSURE_ESCALATION_BLOCKED")
        repaired_text = re.sub(r"لازم\s+تشتري\s+دلوقتي\s*", "", repaired_text, flags=re.I).strip()
        was_repaired = True

    # 6. FALSE EXCLUSIVITY GUARD (Case N)
    if recommendation_decision and getattr(recommendation_decision, "decision", None) == "RECOMMEND_MULTIPLE":
        if re.search(_fold_arabic(r"الوحيد المناسب"), folded, re.I):
            violations.append("FALSE_EXCLUSIVITY_BLOCKED")
            repaired_text = re.sub(r"الوحيد\s+المناسب", "الأنسب من الخيارات المتاحة", repaired_text, flags=re.I).strip()
            was_repaired = True

    # 7. QUESTION BUDGET ENFORCEMENT & CANONICAL REQUIRED QUESTION SELECTION (Case E)
    if policy.question_budget in ["NO_QUESTION", "ONE_IF_REQUIRED"]:
        q_count = repaired_text.count("؟") + repaired_text.count("?")
        if q_count > 1:
            violations.append("EXCESSIVE_QUESTIONS_STYLE_VIOLATION")
            questions = re.findall(r"[^؟?]+[؟?]", repaired_text)
            if questions:
                selected_q = questions[0]
                missing_info = getattr(recommendation_decision, "missing_information", []) or []
                criteria_aliases = {
                    "budget": ["budget", "ميزانية", "ميزانيتك", "سعر"],
                    "headrest": ["headrest", "مسند", "مسند رأس", "رأس"],
                    "color": ["color", "لون", "اللون"],
                    "material": ["material", "خامة", "قماش", "جلد", "شبك", "mesh"],
                    "armrest": ["armrest", "مسند يد", "ذراع", "يدين"],
                }
                found_match = False
                for q in questions:
                    if found_match:
                        break
                    q_fold = _fold_arabic(q)
                    for info in missing_info:
                        if not info:
                            continue
                        info_fold = _fold_arabic(info).lower()
                        aliases = criteria_aliases.get(info_fold, [info_fold])
                        if any(_fold_arabic(alias) in q_fold for alias in aliases):
                            selected_q = q
                            found_match = True
                            break

                non_q_text = re.sub(r"[^؟?]+[؟?]", "", repaired_text).strip()
                if non_q_text:
                    repaired_text = f"{non_q_text} {selected_q.strip()}"
                else:
                    repaired_text = selected_q.strip()
                was_repaired = True

    # 8. PRICE FIRST REORDERING (Case G)
    if policy.answer_order == AnswerOrderMode.PRICE_FIRST:
        price_match = re.search(r"(\d+\s*(جنيه|ج\.م|EGP|\$))", repaired_text, re.I)
        if price_match:
            price_str = price_match.group(0)
            if repaired_text.find(price_str) > 60:
                violations.append("PRICE_NOT_FIRST_VIOLATION")
                repaired_text = f"السعر: {price_str}. " + repaired_text
                was_repaired = True

    status = "REPAIRED" if was_repaired else "PASS"
    return CommunicationStyleAlignmentResult(
        status=status,
        final_answer=repaired_text,
        violations=violations,
        repaired=was_repaired,
    )


def sync_communication_profile_to_db(
    db: Session, company_id: str, lead_id: int, profile_snapshot: CustomerCommunicationProfileSnapshot
) -> bool:
    """
    Persists CustomerCommunicationProfileSnapshot into LeadMemory.preferences JSON column
    under the 'communication_profile' key without overwriting commercial memory items.
    """
    if not db or not lead_id:
        return False

    try:
        from database import Lead, LeadMemory

        mem_row = db.query(LeadMemory).join(Lead, LeadMemory.lead_id == Lead.id).filter(LeadMemory.lead_id == int(lead_id), Lead.company_id == company_id).first()
        if not mem_row:
            mem_row = LeadMemory(lead_id=int(lead_id), preferences="{}")
            db.add(mem_row)

        existing_pref = {}
        if mem_row.preferences:
            try:
                existing_pref = json.loads(mem_row.preferences)
            except Exception:
                existing_pref = {}

        if not isinstance(existing_pref, dict):
            existing_pref = {}

        existing_pref["communication_profile"] = profile_snapshot.to_dict()
        mem_row.preferences = json.dumps(existing_pref, ensure_ascii=False)
        mem_row.last_updated = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as exc:
        log.warning("Failed to sync communication profile to DB for lead %s: %s", lead_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False
