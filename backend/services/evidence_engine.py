import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

log = logging.getLogger("adam.evidence")

EXTRACTOR_VERSION = "evidence_engine_mvp_v1"


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_type: str
    source_text: str
    confidence: float
    normalized_value: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


_PATTERNS: Dict[str, List[re.Pattern]] = {
    "price_question": [
        re.compile(r"\b(what(?:'s| is)?\s+(?:the\s+)?price|price\??|cost\??|how much)\b", re.I),
        re.compile(r"(السعر\s*(?:كام|ايه|إيه)|بكام|بكامل|التكلفة|تكلفته|كم\s+السعر)", re.I),
    ],
    "buying_signal": [
        re.compile(r"\b(send\s+(?:me\s+)?(?:the\s+)?details|details please|available\??|is it available|i want details)\b", re.I),
        re.compile(r"(عايز\s+التفاصيل|عاوز\s+التفاصيل|ابعت\s+العرض|ابعث\s+العرض|ابعت\s+التفاصيل|متاح|متاحة)", re.I),
    ],
    "objection_price": [
        re.compile(r"\b(expensive|too much|discount\??|any discount|price is high)\b", re.I),
        re.compile(r"(غالي|غالية|السعر\s+عالي|السعر\s+غالي|في\s+خصم|فيه\s+خصم|خصم)", re.I),
    ],
    "hesitation": [
        re.compile(r"\b(not now|later|i will think|i'll think|let me think|maybe later)\b", re.I),
        re.compile(r"(هفكر|هفكّر|افكر|أفكر|بعدين|مش\s+دلوقتي|لاحقا|لاحقاً)", re.I),
    ],
    "urgency": [
        re.compile(r"\b(asap|urgent|today|immediately|right now)\b", re.I),
        re.compile(r"(النهارده|اليوم|ضروري|مستعجل|محتاجة\s+النهارده|محتاجه\s+النهارده|محتاج\s+النهارده)", re.I),
    ],
    "start_intent": [
        re.compile(r"\b(how\s+(?:can\s+i\s+)?(?:do\s+i\s+)?(?:start|subscribe|order)|how to start|how do i subscribe|how can i order)\b", re.I),
        re.compile(r"(ابدأ\s+ازاي|أبدأ\s+إزاي|اشترك\s+ازاي|أشترك\s+إزاي|اعمل\s+order\s+ازاي|اعمل\s+اوردر\s+ازاي)", re.I),
    ],
}

_CONFIDENCE = {
    "price_question": 0.95,
    "buying_signal": 0.85,
    "objection_price": 0.9,
    "hesitation": 0.85,
    "urgency": 0.9,
    "start_intent": 0.95,
    "product_mention": 0.85,
}


def _first_match(text: str, patterns: Iterable[re.Pattern]) -> Optional[str]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return None


def _normalize_product_name(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_product_names(products_data: Optional[str]) -> List[str]:
    """
    Parse product names only from structured settings JSON.
    Free-form text is intentionally ignored to avoid verified product hallucination.
    """
    from services.product_context_service import normalize_products_data

    return [product.name for product in normalize_products_data(products_data)]


def _extract_product_mentions(text: str, product_names: Iterable[Any]) -> List[EvidenceCandidate]:
    mentions: List[EvidenceCandidate] = []

    for product in product_names:
        product_name = getattr(product, "name", product)
        normalized = _normalize_product_name(product_name)
        if not normalized:
            continue

        aliases = getattr(product, "aliases", []) or []
        for candidate in [normalized, *aliases]:
            matched_text = _normalize_product_name(candidate)
            if len(matched_text.casefold()) < 2:
                continue

            pattern = r"(?<!\w)" + re.escape(matched_text) + r"(?!\w)"
            if not re.search(pattern, text, flags=re.IGNORECASE):
                continue

            metadata = {
                "matched_product_name": normalized,
                "matched_text": matched_text,
                "match_source": "company_knowledge.products_data",
                "product_confidence": getattr(product, "confidence", 1.0),
            }
            price = getattr(product, "price", None)
            currency = getattr(product, "currency", None)
            missing_data = list(getattr(product, "missing_data", []) or [])
            if missing_data:
                metadata["missing_data"] = missing_data
            if price is not None:
                metadata["known_price"] = price
                metadata["currency"] = currency
                metadata["price_source"] = getattr(product, "source", "products_data")

            mentions.append(
                EvidenceCandidate(
                    evidence_type="product_mention",
                    source_text=matched_text,
                    normalized_value=normalized,
                    confidence=_CONFIDENCE["product_mention"],
                    metadata=metadata,
                )
            )
            break

    return mentions


def _resolved_product_evidence(
    text: str,
    products: Iterable[Any],
    conversation_history: Optional[Iterable[Dict[str, Any]]] = None,
) -> List[EvidenceCandidate]:
    from services.product_context_service import resolve_conversational_product_context

    catalog = list(products)
    context = resolve_conversational_product_context(text, catalog, conversation_history)
    resolved = context.get("resolved_products") or []
    grounded_reasons = {
        "unique_price_reference",
        "prior_assistant_ordinal",
        "prior_assistant_reference",
        "relative_price_reference",
    }
    if context.get("status") != "category_match" and context.get("resolution_reason") not in grounded_reasons:
        return []

    candidates: List[EvidenceCandidate] = []
    for item in resolved:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        metadata = {
            "matched_product_name": name,
            "match_source": "structured_catalog_runtime_resolution",
            "resolution_reason": context.get("resolution_reason") or context.get("status"),
        }
        if item.get("price") is not None:
            metadata["known_price"] = item["price"]
            metadata["currency"] = item.get("currency")
        candidates.append(
            EvidenceCandidate(
                evidence_type="product_mention",
                source_text=text,
                normalized_value=name,
                confidence=_CONFIDENCE["product_mention"],
                metadata=metadata,
            )
        )
    return candidates


def extract_evidence_from_text(
    text: str,
    product_names: Optional[Iterable[Any]] = None,
    conversation_history: Optional[Iterable[Dict[str, Any]]] = None,
) -> List[EvidenceCandidate]:
    if not text or not text.strip():
        return []

    evidence: List[EvidenceCandidate] = []
    for evidence_type, patterns in _PATTERNS.items():
        snippet = _first_match(text, patterns)
        if snippet:
            evidence.append(
                EvidenceCandidate(
                    evidence_type=evidence_type,
                    source_text=snippet,
                    confidence=_CONFIDENCE[evidence_type],
                    metadata={"matched_text": snippet},
                )
            )

    if product_names:
        products = list(product_names)
        evidence.extend(_extract_product_mentions(text, products))
        explicit_names = {candidate.normalized_value for candidate in evidence if candidate.evidence_type == "product_mention"}
        if all(hasattr(product, "name") for product in products):
            evidence.extend(
                candidate
                for candidate in _resolved_product_evidence(text, products, conversation_history)
                if candidate.normalized_value not in explicit_names
            )

    return evidence


def _evidence_hash(candidate: EvidenceCandidate) -> str:
    payload = "|".join(
        [
            candidate.evidence_type,
            candidate.source_text.casefold(),
            (candidate.normalized_value or "").casefold(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_products(db: Session, company_id: str) -> List[Any]:
    from services.product_context_service import get_company_products

    return get_company_products(db, company_id)


def _find_lead_id_for_message(db: Session, company_id: str, user_id: str) -> Optional[int]:
    from database import Lead, get_phone_variants, normalize_whatsapp_number

    base_phone = normalize_whatsapp_number(user_id)
    if str(user_id or "").startswith("wc_v_"):
        lead = (
            db.query(Lead)
            .filter(
                Lead.company_id == company_id,
                Lead.external_customer_id == str(user_id),
                Lead.is_deleted == False,
            )
            .first()
        )
    else:
        lead = (
            db.query(Lead)
            .filter(
                Lead.company_id == company_id,
                (Lead.whatsapp_number == base_phone) | (Lead.phone.in_(get_phone_variants(base_phone))),
                Lead.is_deleted == False,
            )
            .first()
        )
    return lead.id if lead else None


def persist_evidence_for_message(db: Session, message_obj: Any) -> int:
    """
    Extract and persist deterministic message evidence.
    Caller owns the surrounding transaction.
    """
    from database import LeadEvidence

    if not message_obj or message_obj.sender != "user" or message_obj.direction != "incoming":
        return 0

    from database import Message

    products = _load_products(db, message_obj.company_id)
    previous_messages = (
        db.query(Message)
        .filter(
            Message.company_id == message_obj.company_id,
            Message.user_id == message_obj.user_id,
            Message.id <= message_obj.id,
            Message.is_deleted == False,
        )
        .order_by(Message.id.asc())
        .all()
    )
    history = [{"role": row.sender, "content": row.message} for row in previous_messages]
    candidates = extract_evidence_from_text(message_obj.message, product_names=products, conversation_history=history)
    if not candidates:
        return 0

    lead_id = _find_lead_id_for_message(db, message_obj.company_id, message_obj.user_id)
    created = 0

    for candidate in candidates:
        evidence_hash = _evidence_hash(candidate)
        exists = (
            db.query(LeadEvidence.id)
            .filter(
                LeadEvidence.company_id == message_obj.company_id,
                LeadEvidence.message_internal_id == message_obj.internal_message_id,
                LeadEvidence.evidence_type == candidate.evidence_type,
                LeadEvidence.evidence_hash == evidence_hash,
            )
            .first()
        )
        if exists:
            continue

        metadata = {
            "extractor_version": EXTRACTOR_VERSION,
            **candidate.metadata,
        }
        db.add(
            LeadEvidence(
                company_id=message_obj.company_id,
                lead_id=lead_id,
                message_id=message_obj.id,
                message_internal_id=message_obj.internal_message_id,
                evidence_type=candidate.evidence_type,
                source="message",
                source_text=candidate.source_text,
                normalized_value=candidate.normalized_value,
                confidence=float(candidate.confidence),
                metadata_json=json.dumps(metadata, ensure_ascii=False),
                evidence_hash=evidence_hash,
            )
        )
        created += 1

    return created


def link_unassigned_evidence_for_lead(db: Session, company_id: str, lead_id: int, user_id: str) -> int:
    """
    Backfill lead_id for evidence captured before the lead existed.
    Only links rows scoped to the same company and message conversation variants.
    Caller owns the surrounding transaction.
    """
    from database import Lead, LeadEvidence, Message, get_phone_variants, normalize_whatsapp_number

    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id, Lead.is_deleted == False).first()
    if not lead:
        return 0

    identifiers = {user_id, lead.external_customer_id, lead.phone, lead.whatsapp_number, lead.whatsapp_jid}
    message_user_ids = set()
    for identifier in identifiers:
        if not identifier:
            continue
        message_user_ids.add(identifier)
        message_user_ids.update(get_phone_variants(normalize_whatsapp_number(identifier)))

    if not message_user_ids:
        return 0

    messages = (
        db.query(Message.id, Message.internal_message_id)
        .filter(
            Message.company_id == company_id,
            Message.user_id.in_(message_user_ids),
            Message.direction == "incoming",
            Message.sender == "user",
            Message.is_deleted == False,
        )
        .all()
    )
    if not messages:
        return 0

    message_ids = [row.id for row in messages if row.id is not None]
    internal_ids = [row.internal_message_id for row in messages if row.internal_message_id]

    evidence_rows = (
        db.query(LeadEvidence)
        .filter(
            LeadEvidence.company_id == company_id,
            LeadEvidence.lead_id == None,
            (LeadEvidence.message_id.in_(message_ids)) | (LeadEvidence.message_internal_id.in_(internal_ids)),
        )
        .all()
    )

    for evidence in evidence_rows:
        evidence.lead_id = lead_id

    return len(evidence_rows)
