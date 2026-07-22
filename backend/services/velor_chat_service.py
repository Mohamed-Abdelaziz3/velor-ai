import json
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import Company, Lead, LeadEvidence, Message, WorkspaceSuggestedReply, get_phone_variants, normalize_whatsapp_number
from services.customer_interpreter import classify_lead_question, interpret_customer_conversation, render_ask_velor_answer
from services.product_context_service import get_company_products, get_price_for_product, match_product_mentions
from services.workspace_suggestion_service import serialize_suggestion


BUYING_SIGNAL_WEIGHTS = {
    "buying_signal": 4,
    "start_intent": 4,
    "price_question": 3,
    "urgency": 3,
    "product_mention": 2,
    "hesitation": -1,
    "objection_price": -1,
}

IMPORTANT_EVIDENCE_TYPES = set(BUYING_SIGNAL_WEIGHTS) | {"objection_price"}

INSUFFICIENT_CONVERSATION = "لا توجد بيانات كافية من المحادثة بعد."

EVIDENCE_LABELS = {
    "price_question": "سأل عن السعر",
    "product_mention": "ذكر منتجا أو خدمة",
    "objection_price": "اعتراض على السعر",
    "hesitation": "تردد أو تأجيل",
    "urgency": "يريد ردا سريعا",
    "start_intent": "يسأل عن طريقة البدء",
    "buying_signal": "أظهر اهتماما مبدئيا",
    "service_inquiry": "يسأل عن الخدمات",
    "inquired_about_services": "يسأل عن الخدمات",
}

MISSING_DATA_LABELS = {
    "lead_evidence": "إشارات كافية من المحادثة",
    "recent_evidence": "إشارات حديثة من المحادثات",
    "objection_evidence": "اعتراضات واضحة من العملاء",
    "product_mention": "المنتج أو الخدمة",
    "normalized_product_name": "اسم المنتج بشكل واضح",
    "latest_customer_message": "رسالة واضحة من العميل",
    "buying_signal": "إشارة اهتمام واضحة",
    "start_intent": "طريقة البدء",
    "price_question": "سؤال واضح عن السعر",
    "lead_id": "العميل",
    "product": "المنتج أو الخدمة",
    "products": "المنتج أو الخدمة",
    "service": "نوع الخدمة",
    "service_type": "نوع الخدمة",
    "need": "الاحتياج",
    "budget": "الميزانية",
    "timing": "التوقيت",
    "timeline": "التوقيت",
    "quantity": "الكمية",
    "price": "السعر الموثق",
    "currency": "العملة",
}


@dataclass
class VelorResult:
    answer: str
    evidence: List[Dict[str, Any]]
    confidence: float
    missing_data: List[str]
    suggested_action: str
    suggested_reply: Optional[str]
    source_entities: Dict[str, List[Any]]

    def to_dict(self) -> Dict[str, Any]:
        reasoning_summary = (
            "الإجابة مبنية على رسائل وأدلة مرتبطة بهذا العميل داخل الشركة."
            if self.evidence
            else "لا توجد أدلة كافية، لذلك بقيت الإجابة ضمن حدود المعلومة المعروفة."
        )
        payload = {
            "success": True,
            "answer": self.answer,
            "reply": self.answer,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "missing_data": self.missing_data,
            "suggested_action": self.suggested_action,
            "source_entities": self.source_entities,
            "reasoning_summary": reasoning_summary,
            "evidence_refs": [
                {
                    "label": _evidence_label(item.get("type", "")) if isinstance(item, dict) else "دليل من المحادثة",
                    "message_internal_id": item.get("message_internal_id") if isinstance(item, dict) else None,
                }
                for item in self.evidence[:3]
            ],
            "recommended_action": self.suggested_action or None,
            "draft_reply": self.suggested_reply or None,
            "unknowns": self.missing_data,
        }
        if self.suggested_reply:
            payload["suggested_reply"] = self.suggested_reply
        return payload


def _safe_json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _question_text(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip()).casefold()


def _contains_any(text: str, tokens: Iterable[str]) -> bool:
    return any(token.casefold() in text for token in tokens)


def _humanize_missing_data(items: Optional[Iterable[Any]]) -> List[str]:
    cleaned: List[str] = []
    for item in items or []:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        label = MISSING_DATA_LABELS.get(text.casefold(), text)
        if re.search(r"[a-z]+_[a-z0-9_]+", label, re.I):
            label = "بيانات إضافية من المحادثة"
        if label not in cleaned:
            cleaned.append(label)
    return cleaned


def _evidence_label(value: str) -> str:
    return EVIDENCE_LABELS.get((value or "").casefold(), value or "إشارة من المحادثة")


def _normalize_arabic_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _is_greeting_only(value: str) -> bool:
    text = _normalize_arabic_text(value)
    if not text:
        return False
    compact = re.sub(r"[؟?!.,،؛:()[\]{}\"']", " ", text)
    compact = re.sub(r"\s+", " ", compact).strip()
    without_greeting = re.sub(
        r"\b(السلام عليكم|وعليكم السلام|سلام عليكم|سلام|مرحبا|مرحباً|اهلا|أهلا|هلا|هاي|صباح الخير|مساء الخير|استاذي|أستاذي)\b",
        "",
        compact,
        flags=re.I,
    ).strip()
    return len(without_greeting) <= 2 and len(compact.split()) <= 5


def _is_service_inquiry(value: str) -> bool:
    return bool(re.search(r"(خدمات|خدمة|خدماتك|خدماتكم|بتقدموا|تقدمو|تقدمون|ايه المتاح|إيه المتاح|ما المتاح|اعرف خدمات|service|services|what do you offer)", value or "", re.I))


def _is_price_question(value: str) -> bool:
    return bool(re.search(r"(سعر|السعر|اسعار|أسعار|بكام|كام\b|الثمن|تكلفة|price|cost)", value or "", re.I))


def _clean_product_names(evidence_rows: List[LeadEvidence]) -> List[str]:
    names: List[str] = []
    for row in evidence_rows:
        if row.evidence_type != "product_mention":
            continue
        metadata = _safe_json_loads(row.metadata_json, {})
        name = metadata.get("matched_product_name") or row.normalized_value
        if name and name not in names:
            names.append(str(name))
    return names[:3]


def _conversation_insight(messages: List[Message], evidence_rows: List[LeadEvidence], suggestion: Optional[WorkspaceSuggestedReply] = None) -> Dict[str, Any]:
    customer_texts = [_normalize_arabic_text(msg.message) for msg in messages if msg.sender == "user" and getattr(msg, "message", None)]
    latest_customer = customer_texts[-1] if customer_texts else ""
    joined_customer = " ".join(customer_texts)
    evidence_types = {row.evidence_type for row in evidence_rows}
    product_names = _clean_product_names(evidence_rows)
    suggestion_missing = _safe_json_loads(suggestion.missing_data, []) if suggestion else []

    if not customer_texts and not evidence_rows and not suggestion:
        return {
            "state": INSUFFICIENT_CONVERSATION,
            "summary": INSUFFICIENT_CONVERSATION,
            "confidence_label": "منخفضة",
            "confidence": 0.2,
            "missing_data": ["رسالة واضحة من العميل"],
            "best_next_step": "انتظر رسالة جديدة من العميل قبل الاستنتاج.",
            "expected_next": INSUFFICIENT_CONVERSATION,
            "suggested_reply": None,
            "has_context": False,
        }

    has_price = _is_price_question(joined_customer) or "price_question" in evidence_types
    has_service = _is_service_inquiry(joined_customer) or evidence_types & {"service_inquiry", "inquired_about_services"}
    greeting_only = bool(customer_texts) and all(_is_greeting_only(text) for text in customer_texts)

    if has_price:
        missing = []
        if not product_names:
            missing.append("المنتج أو الخدمة")
        missing.append("الكمية")
        missing.extend(_humanize_missing_data(suggestion_missing))
        return {
            "state": "يسأل عن السعر",
            "summary": "العميل يسأل عن السعر. لا يجب عرض رقم إلا إذا كان المنتج والسعر معروفين من سياق المنتجات الموثق.",
            "confidence_label": "متوسطة" if customer_texts else "منخفضة",
            "confidence": 0.62 if customer_texts else 0.45,
            "missing_data": missing,
            "best_next_step": "اسأل عن المنتج أو الكمية قبل عرض السعر إذا لم يكونا واضحين.",
            "expected_next": "العميل ينتظر توضيحا دقيقا للتكلفة بعد تحديد السياق.",
            "suggested_reply": suggestion.suggested_reply if suggestion else None,
            "has_context": True,
        }

    if has_service:
        missing = ["نوع الخدمة", "الميزانية", "التوقيت"] + _humanize_missing_data(suggestion_missing)
        return {
            "state": "يستكشف الخدمات",
            "summary": "العميل سأل عن الخدمات بشكل عام ولم يحدد احتياجا واضحا بعد.",
            "confidence_label": "متوسطة",
            "confidence": 0.6,
            "missing_data": missing,
            "best_next_step": "اسأله عن نوع الخدمة التي يحتاجها أو المشكلة التي يريد حلها.",
            "expected_next": "نحتاج إجابة من العميل لتحديد العرض المناسب.",
            "suggested_reply": suggestion.suggested_reply if suggestion else None,
            "has_context": True,
        }

    if greeting_only:
        missing = ["نوع الخدمة", "الاحتياج", "الميزانية", "التوقيت"] + _humanize_missing_data(suggestion_missing)
        return {
            "state": "تحية فقط",
            "summary": "المحادثة ما زالت في مرحلة التحية فقط. لا توجد نية شراء واضحة بعد.",
            "confidence_label": "متوسطة",
            "confidence": 0.55,
            "missing_data": missing,
            "best_next_step": "انتظر رد العميل أو اسأله سؤالا افتتاحيا بسيطا عند تولي المحادثة.",
            "expected_next": "نحتاج رسالة جديدة لفهم الاحتياج.",
            "suggested_reply": suggestion.suggested_reply if suggestion else None,
            "has_context": True,
        }

    if product_names:
        missing = ["الكمية", "الميزانية", "التوقيت"] + _humanize_missing_data(suggestion_missing)
        return {
            "state": "مهتم مبدئيا",
            "summary": f"يوجد اهتمام بمنتج أو خدمة مذكورة في المحادثة: {', '.join(product_names)}. لا توجد نية شراء مؤكدة بعد.",
            "confidence_label": "متوسطة",
            "confidence": 0.62,
            "missing_data": missing,
            "best_next_step": "اسأل عن الاحتياج أو الكمية لتحديد الخطوة التالية.",
            "expected_next": "قد يوضح العميل احتياجه أو يسأل عن السعر.",
            "suggested_reply": suggestion.suggested_reply if suggestion else None,
            "has_context": True,
        }

    if customer_texts:
        missing = ["نوع الخدمة", "الاحتياج", "الميزانية", "التوقيت"] + _humanize_missing_data(suggestion_missing)
        state = "يحتاج توضيح" if latest_customer and len(latest_customer.split()) <= 4 else "لا توجد نية واضحة بعد"
        return {
            "state": state,
            "summary": "توجد رسائل من العميل، لكنها لا تحدد احتياجا أو منتجا أو نية شراء واضحة بعد.",
            "confidence_label": "منخفضة",
            "confidence": 0.4,
            "missing_data": missing,
            "best_next_step": "اطلب توضيحا قصيرا من العميل عن الخدمة أو المنتج الذي يحتاجه.",
            "expected_next": "نحتاج رسالة أوضح لفهم الاحتياج.",
            "suggested_reply": suggestion.suggested_reply if suggestion else None,
            "has_context": True,
        }

    missing = _humanize_missing_data(suggestion_missing) or ["رسالة واضحة من العميل"]
    return {
        "state": "لا توجد نية واضحة بعد",
        "summary": "توجد بعض الإشارات المساعدة، لكن لا توجد رسائل كافية لتفسير الاحتياج بثقة.",
        "confidence_label": "منخفضة",
        "confidence": 0.35,
        "missing_data": missing,
        "best_next_step": "انتظر رسالة أوضح من العميل قبل افتراض المنتج أو السعر.",
        "expected_next": "نحتاج تفاعلا جديدا من العميل.",
        "suggested_reply": suggestion.suggested_reply if suggestion else None,
        "has_context": True,
    }


def _structured_lead_answer(insight: Dict[str, Any]) -> str:
    missing = "، ".join(_humanize_missing_data(insight.get("missing_data"))) or "لا توجد بيانات ناقصة واضحة"
    parts = [
        "الخلاصة",
        f"{insight['state']}: {insight['summary']}",
        "",
        "ماذا فهمت من المحادثة؟",
        insight["summary"],
        "",
        "مستوى الثقة",
        insight["confidence_label"],
        "",
        "البيانات الناقصة",
        missing,
        "",
        "أفضل خطوة الآن",
        insight["best_next_step"],
    ]
    if insight.get("suggested_reply"):
        parts.extend(["", "رد مقترح", insight["suggested_reply"]])
    return "\n".join(parts)


def classify_intent(message: str, scope: str = "company") -> str:
    text = _question_text(message)
    if _contains_any(text, ["أرد", "ارد", "أفضل رد", "افضل رد", "اكتبلي", "what should i say", "best reply", "reply for"]):
        return "best_reply"
    if _contains_any(text, ["أقرب", "اقرب", "جاهز", "هوت", "hottest", "closest", "ready to close", "closest to buying"]):
        return "closest_lead"
    if _contains_any(text, ["اعتراض", "اعتراضات", "hesitat", "objection", "why are customers", "سبب بيضيع"]):
        return "common_objection"
    if _contains_any(text, ["price", "سعر", "السعر", "كام", "تكلفة", "cost"]):
        return "price_question"
    if _contains_any(text, ["منتج", "product", "asked about", "بتسأل عنه", "اتذكر"]):
        return "product_asked"
    if _contains_any(text, ["لخص", "ملخص", "focus", "summarize", "what matters", "ركز"]):
        return "summary"
    return "lead_summary" if scope == "lead" else "summary"


def _serialize_evidence(row: LeadEvidence) -> Dict[str, Any]:
    return {
        "id": row.id,
        "lead_id": row.lead_id,
        "type": row.evidence_type,
        "source_text": row.source_text,
        "normalized_value": row.normalized_value,
        "source_message_internal_id": row.message_internal_id,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _lead_name(lead: Optional[Lead]) -> str:
    if not lead:
        return "العميل"
    return lead.name or lead.phone or lead.whatsapp_number or f"Lead {lead.id}"


def _lead_user_ids(lead: Lead) -> List[str]:
    ids = set()
    for value in (lead.phone, lead.whatsapp_number, lead.whatsapp_jid, lead.customer_provided_phone):
        if value:
            ids.add(value)
            ids.update(get_phone_variants(normalize_whatsapp_number(value)))
    return [item for item in ids if item]


def _recent_messages_for_lead(db: Session, company_id: str, lead: Lead, limit: int = 20) -> List[Message]:
    user_ids = _lead_user_ids(lead)
    if not user_ids:
        return []
    rows = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.user_id.in_(user_ids))
        .order_by(desc(Message.created_at))
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows


def _recent_evidence_for_lead(db: Session, company_id: str, lead_id: int, limit: int = 30) -> List[LeadEvidence]:
    return (
        db.query(LeadEvidence)
        .filter(LeadEvidence.company_id == company_id, LeadEvidence.lead_id == lead_id)
        .order_by(desc(LeadEvidence.created_at))
        .limit(limit)
        .all()
    )


def _recent_company_evidence(db: Session, company_id: str, limit: int = 100) -> List[LeadEvidence]:
    return (
        db.query(LeadEvidence)
        .join(Lead, Lead.id == LeadEvidence.lead_id)
        .filter(
            LeadEvidence.company_id == company_id,
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
        .order_by(desc(LeadEvidence.created_at))
        .limit(limit)
        .all()
    )


def _active_suggestion_for_lead(db: Session, company_id: str, lead_id: int) -> Optional[WorkspaceSuggestedReply]:
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead:
        return None
    from services.workspace_suggestion_service import active_workspace_suggestions

    active = active_workspace_suggestions(db, company_id, lead, limit=1)
    return active[0] if active else None


def _result(
    answer: str,
    evidence: List[LeadEvidence],
    confidence: float,
    missing_data: Optional[List[str]] = None,
    suggested_action: str = "",
    suggested_reply: Optional[str] = None,
    lead_ids: Optional[List[int]] = None,
    product_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return VelorResult(
        answer=answer,
        evidence=[_serialize_evidence(row) for row in evidence[:8]],
        confidence=max(0.0, min(1.0, confidence)),
        missing_data=sorted(set(_humanize_missing_data(missing_data))),
        suggested_action=suggested_action,
        suggested_reply=suggested_reply,
        source_entities={
            "lead_ids": lead_ids or sorted({row.lead_id for row in evidence if row.lead_id}),
            "product_names": product_names or sorted({row.normalized_value for row in evidence if row.evidence_type == "product_mention" and row.normalized_value}),
        },
    ).to_dict()


def answer_closest_lead(db: Session, company_id: str) -> Dict[str, Any]:
    evidence_rows = [row for row in _recent_company_evidence(db, company_id, 120) if row.evidence_type in IMPORTANT_EVIDENCE_TYPES]
    scores: Dict[int, int] = defaultdict(int)
    grouped: Dict[int, List[LeadEvidence]] = defaultdict(list)
    for row in evidence_rows:
        if not row.lead_id:
            continue
        scores[row.lead_id] += BUYING_SIGNAL_WEIGHTS.get(row.evidence_type, 0)
        grouped[row.lead_id].append(row)

    if not scores:
        return _result(
            "البيانات غير كافية لتحديد أقرب عميل للشراء. لا توجد إشارات شراء موثقة حديثة.",
            [],
            0.2,
            ["buying_signal", "start_intent", "price_question"],
            "راجع المحادثات الجديدة أو انتظر إشارات أوضح قبل ترتيب الأولويات.",
        )

    lead_id, score = max(scores.items(), key=lambda item: item[1])
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    selected = grouped[lead_id]
    evidence_types = [_evidence_label(row.evidence_type) for row in selected[:4]]
    product_names = sorted({row.normalized_value for row in selected if row.evidence_type == "product_mention" and row.normalized_value})
    missing = []
    if not product_names:
        missing.append("product")
    missing.append("quantity")
    answer = (
        f"الأقرب حسب البيانات المتاحة هو {_lead_name(lead)}. "
        f"السبب: ظهرت إشارات موثقة مثل {', '.join(evidence_types)}. "
        "هذا ترجيح مبني على الإشارات وليس تأكيدا للإغلاق."
    )
    return _result(
        answer,
        selected,
        0.55 + min(score, 10) / 25,
        missing,
        "ابدأ برد يدوي قصير يطلب تأكيد المنتج والكمية أو الخطوة التالية.",
        lead_ids=[lead_id],
        product_names=product_names,
    )


def answer_common_objection(db: Session, company_id: str) -> Dict[str, Any]:
    evidence_rows = (
        db.query(LeadEvidence)
        .join(Lead, Lead.id == LeadEvidence.lead_id)
        .filter(
            LeadEvidence.company_id == company_id,
            LeadEvidence.evidence_type.in_(["objection_price", "hesitation"]),
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
        .order_by(desc(LeadEvidence.created_at))
        .limit(80)
        .all()
    )
    if not evidence_rows:
        return _result(
            "لا توجد اعتراضات متكررة موثقة كفاية حتى الآن.",
            [],
            0.25,
            ["objection_evidence"],
            "استمر في جمع المحادثات، ثم راجع اعتراضات السعر أو التردد عند ظهورها.",
        )

    counts = Counter(row.evidence_type for row in evidence_rows)
    top_type, top_count = counts.most_common(1)[0]
    label = "اعتراض السعر" if top_type == "objection_price" else "التردد قبل القرار"
    answer = f"أكثر نمط متكرر حسب الأدلة هو {label}، وظهر {top_count} مرة في الأدلة الحديثة. لا أعتبره سبب خسارة بيع إلا إذا وُجدت بيانات صفقات مغلقة أو مفقودة."
    return _result(
        answer,
        [row for row in evidence_rows if row.evidence_type == top_type],
        0.7,
        [],
        "جهز ردودا مختصرة تعالج هذا الاعتراض وتطلب المنتج أو الكمية عند نقص البيانات.",
    )


def answer_product_asked(db: Session, company_id: str) -> Dict[str, Any]:
    evidence_rows = (
        db.query(LeadEvidence)
        .join(Lead, Lead.id == LeadEvidence.lead_id)
        .filter(
            LeadEvidence.company_id == company_id,
            LeadEvidence.evidence_type == "product_mention",
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
        .order_by(desc(LeadEvidence.created_at))
        .limit(100)
        .all()
    )
    if not evidence_rows:
        return _result(
            "لا أستطيع تحديد أكثر منتج مطلوب بعد. لا توجد إشارات كافية عن ذكر المنتجات أو الخدمات.",
            [],
            0.25,
            ["product_mention"],
            "تأكد أن المنتجات معرفة في Product/Pricing Context حتى يتم ربط ذكر المنتجات بالأدلة.",
        )

    counts = Counter(row.normalized_value for row in evidence_rows if row.normalized_value)
    if not counts:
        return _result(
            "توجد إشارات منتجات، لكن أسماء المنتجات غير منظمة بما يكفي للترتيب.",
            evidence_rows,
            0.35,
            ["normalized_product_name"],
            "راجع إعدادات المنتجات والأسماء البديلة.",
        )
    product, count = counts.most_common(1)[0]
    answer = f"أكثر منتج تم السؤال أو الذكر عنه حسب إشارات المحادثات هو {product}، وظهر {count} مرة في الأدلة الحديثة. هذا ترتيب للأسئلة والذكر فقط وليس تقرير مبيعات."
    return _result(answer, [row for row in evidence_rows if row.normalized_value == product], 0.75, [], "راجع العملاء الذين ذكروا هذا المنتج ورد عليهم بعرض واضح.", product_names=[product])


def answer_price_question(db: Session, company_id: str, message: str) -> Dict[str, Any]:
    products = get_company_products(db, company_id)
    matches = match_product_mentions(message, products)
    if not matches:
        return _result(
            "أحتاج اسم المنتج أو الخدمة قبل ذكر أي سعر. لا يوجد منتج موثوق محدد في السؤال.",
            [],
            0.5,
            ["product", "price"],
            "اسأل عن اسم المنتج المطلوب أو حدده من القائمة الموثقة.",
        )

    product = matches[0]
    price = get_price_for_product(product)
    if price["price"] is None:
        return _result(
            f"المنتج {product.name} موجود في السياق الموثق، لكن السعر غير معروف، لذلك لن أخترع سعرا.",
            [],
            0.75,
            price["missing_data"],
            "حدّث Product/Pricing Context بسعر موثوق قبل استخدامه في الردود.",
            product_names=[product.name],
        )

    currency = f" {price['currency']}" if price.get("currency") else ""
    missing = price.get("missing_data") or []
    answer = f"السعر الموثق لـ {product.name} هو {price['price']:g}{currency} حسب Product/Pricing Context."
    return _result(answer, [], 0.9, missing, "استخدم السعر فقط مع توضيح أن الكمية أو الباقة قد تغير التفاصيل.", product_names=[product.name])


def _messages_from_context(conversation_context: Optional[List[Dict[str, Any]]]) -> List[Any]:
    """Convert frontend conversation_context into SimpleNamespace objects
    compatible with the existing message analysis pipeline.
    Only includes actual chat messages (type='message' or no type)."""
    if not conversation_context:
        return []
    result = []
    for item in conversation_context:
        msg_type = item.get("type", "message")
        text = (item.get("message") or "").strip()
        if msg_type != "message" or not text:
            continue
        sender = item.get("sender", "user")
        direction = (item.get("direction") or "").lower()
        # Map direction/is_ai to sender for backend compatibility
        if direction == "incoming" or sender in ("user", "customer"):
            sender = "user"
        elif item.get("is_ai") or sender in ("assistant", "bot", "velor"):
            sender = "assistant"
        elif direction == "outgoing" or sender in ("owner", "agent", "human", "manual"):
            sender = "owner"
        result.append(SimpleNamespace(sender=sender, message=text))
    return result


def answer_best_reply_for_lead(db: Session, company_id: str, lead_id: int, conversation_context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead:
        raise ValueError("lead_not_found")

    suggestion = _active_suggestion_for_lead(db, company_id, lead_id)
    evidence_rows = _recent_evidence_for_lead(db, company_id, lead_id, 30)
    if suggestion:
        missing = _safe_json_loads(suggestion.missing_data, [])
        answer = f"أفضل رد آمن حاليا هو الرد المقترح الموجود للعميل {_lead_name(lead)}. لم يتم إرساله تلقائيا."
        return _result(
            answer,
            evidence_rows,
            suggestion.confidence or 0.75,
            missing,
            suggestion.why_this_reply or "انسخ الرد أو عدله يدويا قبل الإرسال.",
            suggested_reply=suggestion.suggested_reply,
            lead_ids=[lead_id],
        )

    messages = _recent_messages_for_lead(db, company_id, lead, 10)
    if not messages and lead.last_message:
        messages = [
            SimpleNamespace(
                sender=lead.last_message_sender or "user",
                message=lead.last_message,
            )
        ]
    if not messages and not evidence_rows:
        return _result(
            "لا توجد محادثة أو أدلة كافية لاقتراح رد محدد لهذا العميل.",
            [],
            0.25,
            ["latest_customer_message"],
            "اطلب من العميل توضيح احتياجه قبل محاولة الإغلاق.",
            lead_ids=[lead_id],
        )

    products = get_company_products(db, company_id)
    interpretation = interpret_customer_conversation(
        messages=messages,
        evidence_rows=evidence_rows,
        suggestion=None,
        lead=lead,
        product_context=products,
    )
    reply = interpretation.safe_suggested_reply or "ممكن توضح لي المنتج أو الخدمة التي تحتاجها والكمية المتوقعة حتى أساعدك بدقة؟"

    return _result(
        "اقترحت ردًا آمنًا بناءً على فهم المحادثة. لم يتم إرساله تلقائيًا.",
        evidence_rows,
        max(0.55, interpretation.confidence_score),
        interpretation.missing_data,
        "راجع الرد وعدّله يدويًا قبل الإرسال.",
        suggested_reply=reply,
        lead_ids=[lead_id],
    )


def answer_lead_summary(db: Session, company_id: str, lead_id: int, user_question: str = "لخص حالة العميل", conversation_context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead:
        raise ValueError("lead_not_found")
    evidence_rows = _recent_evidence_for_lead(db, company_id, lead_id, 30)
    messages = _recent_messages_for_lead(db, company_id, lead, 20)
    if not messages and lead.last_message:
        messages = [
            SimpleNamespace(
                sender=lead.last_message_sender or "user",
                message=lead.last_message,
            )
        ]
    suggestion = _active_suggestion_for_lead(db, company_id, lead_id)
    products = get_company_products(db, company_id)
    interpretation = interpret_customer_conversation(
        messages=messages,
        evidence_rows=evidence_rows,
        suggestion=suggestion,
        lead=lead,
        memory=getattr(lead, "memory", None),
        product_context=products,
    )

    question = _question_text(user_question)
    customer_messages = [row for row in messages if str(getattr(row, "sender", "")).casefold() in {"user", "customer"}]
    latest_customer_message = customer_messages[-1] if customer_messages else None
    evidence_refs = [
        {"type": _evidence_label(row.evidence_type), "message_internal_id": row.message_internal_id}
        for row in evidence_rows[:3]
    ]

    if _contains_any(question, ("last unanswered", "آخر سؤال لم نجب", "آخر سؤال ما اتردش", "اخر سؤال لم نجب")):
        if not latest_customer_message:
            return _result("لا توجد رسالة عميل يمكن اعتبارها سؤالًا مفتوحًا بعد.", [], 0.5, ["latest_customer_message"], "انتظر رسالة واضحة من العميل.")
        last_index = max(index for index, row in enumerate(messages) if row is latest_customer_message)
        answered = any(
            str(getattr(row, "sender", "")).casefold() in {"assistant", "owner", "human"}
            for row in messages[last_index + 1:]
        )
        if answered:
            return _result("لا يوجد سؤال مفتوح ظاهر في آخر دور؛ وصلت بعده استجابة مسجلة.", evidence_rows[:3], 0.76, [], "راقب الرسالة التالية فقط.")
        return _result(
            f"آخر سؤال لم يُجب عنه هو: «{getattr(latest_customer_message, 'message', '')}»." ,
            evidence_rows[:3], 0.86, [], "أجب عن هذا السؤال أولًا قبل طلب معلومات جديدة.", lead_ids=[lead_id],
        )

    if _contains_any(question, ("ليه محتاج تدخلي", "لماذا يحتاج تدخلي", "why intervention", "why do i need")):
        reasons = []
        if lead.is_paused:
            reasons.append("التولي البشري مفعّل")
        if any(row.evidence_type == "objection_price" for row in evidence_rows):
            reasons.append("هناك اعتراض مسجل على السعر")
        if latest_customer_message:
            reasons.append("آخر رسالة تحتاج مراجعة مباشرة")
        answer = "تدخلك مطلوب لأن " + "، ".join(reasons) + "." if reasons else "لا توجد إشارة موثقة تستدعي تدخلك الآن."
        return _result(answer, evidence_rows[:3], 0.78, [], "راجع الرد المقترح قبل الإرسال.", lead_ids=[lead_id])

    if _contains_any(question, ("مناسب لميزانيته", "يناسب ميزانيته", "within budget", "budget fit")):
        from services.product_context_service import resolve_conversational_product_context
        history = [{"sender": getattr(row, "sender", ""), "message": getattr(row, "message", "")} for row in messages]
        resolved = resolve_conversational_product_context(getattr(latest_customer_message, "message", ""), products, history)
        selected = (resolved.get("resolved_products") or [None])[0]
        budget_raw = getattr(getattr(lead, "memory", None), "budget", "")
        budget_values = re.findall(r"\d+(?:\.\d+)?", str(budget_raw or ""))
        budget = float(budget_values[-1]) if budget_values else None
        if selected and selected.get("price") is not None and budget is not None:
            if selected["price"] <= budget:
                answer = f"نعم، {selected['name']} بسعر {selected['price']:g} {selected.get('currency') or 'EGP'} داخل ميزانيته المسجلة ({budget:g} EGP)."
            else:
                answer = f"لا، {selected['name']} بسعر {selected['price']:g} {selected.get('currency') or 'EGP'} أعلى من ميزانيته المسجلة ({budget:g} EGP)."
            return _result(answer, evidence_rows[:3], 0.9, [], "اعرض فقط الخيارات داخل الميزانية.", lead_ids=[lead_id])
        return _result("لا أستطيع تأكيد الملاءمة: يلزم سعر منتج محدد وميزانية صريحة.", evidence_rows[:3], 0.55, ["product", "budget"], "اسأل عن المعلومة الناقصة مرة واحدة.", lead_ids=[lead_id])

    if _contains_any(question, ("جهز", "رد طبيعي", "draft reply", "prepare a reply")) and latest_customer_message and isinstance(latest_customer_message, Message):
        from services.velor_chat_v2 import build_response_context, build_response_plan, execute_contextual_fallback
        company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
        if company:
            ctx = build_response_context(db, latest_customer_message, company, lead)
            plan = build_response_plan(ctx)
            draft = execute_contextual_fallback(ctx, plan)
            return _result("هذا رد مقترح على آخر رسالة؛ راجعه أو عدّله قبل الإرسال.", evidence_rows[:3], 0.84, [], "استخدم الرد في المحرر، ولا يُرسل تلقائيًا.", suggested_reply=draft, lead_ids=[lead_id])

    if interpretation.insufficient_data:
        return _result(
            render_ask_velor_answer("لخص حالة العميل", interpretation),
            [],
            interpretation.confidence_score,
            interpretation.missing_data,
            interpretation.next_best_action,
            lead_ids=[lead_id],
        )

    answer = _answer_grounded_lead_question(user_question, messages, evidence_rows, products)
    if not answer:
        answer = render_ask_velor_answer(user_question, interpretation)
    return _result(
        answer,
        evidence_rows,
        interpretation.confidence_score,
        interpretation.missing_data,
        interpretation.next_best_action,
        suggested_reply=interpretation.safe_suggested_reply if classify_lead_question(user_question) == "reply" else None,
        lead_ids=[lead_id],
    )


def answer_summary(db: Session, company_id: str) -> Dict[str, Any]:
    evidence_rows = _recent_company_evidence(db, company_id, 100)
    if not evidence_rows:
        return _result(
            "لا توجد بيانات كافية لتلخيص حالة المبيعات الآن.",
            [],
            0.2,
            ["recent_evidence"],
            "ابدأ بجمع محادثات العملاء وربط المنتجات بالسياق الموثق.",
        )
    counts = Counter(row.evidence_type for row in evidence_rows)
    top = counts.most_common(3)
    answer = "أهم ما يظهر الآن: " + "، ".join([f"{_evidence_label(name)} ({count})" for name, count in top]) + ". ركز على الإشارات الأعلى عددا وردود العملاء المنتظرين."
    return _result(answer, evidence_rows, 0.6, [], "ابدأ بالعملاء أصحاب سؤال السعر وطريقة البدء ثم عالج اعتراضات السعر.", product_names=sorted({row.normalized_value for row in evidence_rows if row.evidence_type == "product_mention" and row.normalized_value}))


async def ask_velor(db: Session, company_id: str, message: str, scope: str = "company", lead_id: Optional[int] = None, conversation_context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    normalized_scope = "lead" if lead_id or scope == "lead" else "company"
    if normalized_scope == "company":
        from services.commercial_intelligence_service import answer_business_question

        business_payload = answer_business_question(db, company_id, message)
        if business_payload is not None:
            business_payload.setdefault("reasoning_summary", "الإجابة مشتقة من أحداث تجارية محددة ومرتبطة بمصادر، وليست توقع مبيعات.")
            business_payload.setdefault("evidence_refs", business_payload.get("evidence") or [])
            business_payload.setdefault("recommended_action", business_payload.get("suggested_action") or None)
            business_payload.setdefault("draft_reply", business_payload.get("suggested_reply") or None)
            business_payload.setdefault("unknowns", business_payload.get("missing_data") or [])
            return business_payload
    intent = classify_intent(message, normalized_scope)

    try:
        if normalized_scope == "lead":
            if not lead_id:
                return _result("أحتاج تحديد العميل قبل الإجابة عن سؤال مرتبط بمحادثة معينة.", [], 0.3, ["lead_id"], "افتح مساحة عمل العميل أو أرسل lead_id.")
            if intent == "best_reply":
                payload = answer_best_reply_for_lead(db, company_id, lead_id, conversation_context=conversation_context)
            else:
                payload = answer_lead_summary(db, company_id, lead_id, user_question=message, conversation_context=conversation_context)
        elif intent == "closest_lead":
            payload = answer_closest_lead(db, company_id)
        elif intent == "common_objection":
            payload = answer_common_objection(db, company_id)
        elif intent == "product_asked":
            payload = answer_product_asked(db, company_id)
        elif intent == "price_question":
            payload = answer_price_question(db, company_id, message)
        elif intent == "best_reply":
            payload = _result("أحتاج فتح عميل محدد حتى أقترح أفضل رد بدون خلط بيانات العملاء.", [], 0.3, ["lead_id"], "افتح Workspace الخاص بالعميل ثم اسأل فيلور.")
        else:
            payload = answer_summary(db, company_id)
    except ValueError as exc:
        if str(exc) == "lead_not_found":
            raise
        raise

    payload["intent"] = intent
    payload["scope"] = normalized_scope
    payload["llm_used"] = False
    payload["grounding"] = "deterministic_retrieval"
    # Additive contextual-assistant contract. Existing UI consumers retain the
    # original fields while newer surfaces can render compact evidence chips.
    payload["evidence_refs"] = [
        {
            "label": _evidence_label(item.get("type", "")) if isinstance(item, dict) else "دليل من المحادثة",
            "message_internal_id": item.get("message_internal_id") if isinstance(item, dict) else None,
        }
        for item in (payload.get("evidence") or [])[:3]
    ]
    payload["recommended_action"] = payload.get("suggested_action") or None
    payload["draft_reply"] = payload.get("suggested_reply") or None
    payload["unknowns"] = payload.get("missing_data") or []
    return payload


def _lead_question_kind(question: str) -> str:
    text = _question_text(question)
    checks = (
        ("latest_request", ("latest request", "last request", "\u0622\u062e\u0631 \u0637\u0644\u0628", "\u0627\u062e\u0631 \u0637\u0644\u0628")),
        ("products_seen", ("products seen", "products viewed", "which products", "\u0627\u0644\u0645\u0646\u062a\u062c\u0627\u062a \u0627\u0644\u062a\u064a \u0634\u0627\u0647\u062f", "\u0627\u0644\u0645\u0646\u062a\u062c\u0627\u062a \u0627\u0644\u0644\u064a \u0634\u0627\u0641\u0647\u0627", "\u0627\u062a\u0643\u0644\u0645 \u0639\u0646", "\u0627\u064a \u0645\u0646\u062a\u062c\u0627\u062a", "\u0627\u0646\u0647\u064a \u0645\u0646\u062a\u062c\u0627\u062a", "\u0627\u0646\u064a \u0645\u0646\u062a\u062c\u0627\u062a")),
        ("important_notes", ("important notes", "key notes", "\u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0627\u0644\u0645\u0647\u0645\u0629", "\u0627\u0647\u0645 \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a")),
        ("important_criteria", ("important criteria", "important specs", "requirements", "\u0627\u0644\u0645\u0648\u0627\u0635\u0641\u0627\u062a \u0627\u0644\u0645\u0647\u0645\u0629", "\u0627\u0644\u0645\u0639\u0627\u064a\u064a\u0631")),
        ("main_interest", ("main interest", "\u0627\u0647\u062a\u0645\u0627\u0645\u0647 \u0627\u0644\u0631\u0626\u064a\u0633\u064a", "\u0627\u0647\u062a\u0645\u0627\u0645\u0647")),
    )
    for kind, terms in checks:
        if _contains_any(text, terms):
            return kind
    return ""


def _message_history(messages: List[Any]) -> List[Dict[str, Any]]:
    return [{"role": getattr(row, "sender", ""), "content": getattr(row, "message", "")} for row in messages]


def _products_seen_in_conversation(messages: List[Any], evidence_rows: List[LeadEvidence], products: List[Any]) -> List[str]:
    seen = _clean_product_names(evidence_rows)
    for message in messages:
        for product in match_product_mentions(getattr(message, "message", ""), products):
            if product.name not in seen:
                seen.append(product.name)
    return seen[:6]


def _expressed_criteria(customer_messages: List[str]) -> List[str]:
    joined = " ".join(customer_messages).casefold()
    criteria = []
    checks = (
        ("\u0631\u0627\u062d\u0629 \u0644\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0627\u0644\u0637\u0648\u064a\u0644", ("long hours", "long sitting", "\u0634\u063a\u0644 \u0643\u062a\u064a\u0631", "\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0637\u0648\u064a\u0644", "\u0645\u0631\u064a\u062d")),
        ("\u0645\u064a\u0632\u0627\u0646\u064a\u0629 \u0645\u062d\u062f\u062f\u0629", ("budget", "\u0645\u064a\u0632\u0627\u0646\u064a\u0629", "\u063a\u0627\u0644\u064a", "\u0631\u062e\u064a\u0635")),
        ("\u0644\u0648\u0646 \u0645\u062d\u062f\u062f", ("color", "\u0644\u0648\u0646", "\u0627\u0633\u0648\u062f", "\u0631\u0645\u0627\u062f\u064a")),
    )
    for label, terms in checks:
        if _contains_any(joined, terms):
            criteria.append(label)
    return criteria


def _answer_grounded_lead_question(question: str, messages: List[Any], evidence_rows: List[LeadEvidence], products: List[Any]) -> Optional[str]:
    kind = _lead_question_kind(question)
    if not kind:
        return None

    customer_messages = [str(getattr(row, "message", "")).strip() for row in messages if getattr(row, "sender", "") == "user" and getattr(row, "message", None)]
    latest_customer = customer_messages[-1] if customer_messages else ""
    from services.product_context_service import resolve_conversational_product_context

    latest_context = resolve_conversational_product_context(latest_customer, products, _message_history(messages)) if latest_customer else {}
    latest_products = [item.get("name") for item in latest_context.get("resolved_products", []) if item.get("name")]
    seen_products = _products_seen_in_conversation(messages, evidence_rows, products)
    evidence_types = {row.evidence_type for row in evidence_rows}

    if kind == "latest_request":
        if not latest_customer:
            return "\u0644\u0627 \u062a\u0648\u062c\u062f \u0631\u0633\u0627\u0644\u0629 \u0639\u0645\u064a\u0644 \u0645\u0633\u062c\u0644\u0629 \u064a\u0645\u0643\u0646 \u0627\u0639\u062a\u0628\u0627\u0631\u0647\u0627 \u0627\u0644\u0637\u0644\u0628 \u0627\u0644\u0623\u062e\u064a\u0631."
        suffix = f" \u0648\u0627\u0644\u0645\u0642\u0635\u0648\u062f \u0645\u0646\u0647\u0627: {', '.join(latest_products)}." if latest_products else ""
        return f"\u0622\u062e\u0631 \u0637\u0644\u0628 \u0641\u0639\u0644\u064a \u0645\u0646 \u0627\u0644\u0639\u0645\u064a\u0644 \u0647\u0648: \u00ab{latest_customer}\u00bb.{suffix}"
    if kind == "products_seen":
        return ("\u0627\u0644\u0645\u0646\u062a\u062c\u0627\u062a \u0627\u0644\u062a\u064a \u0638\u0647\u0631\u062a \u0641\u0639\u0644\u064a\u064b\u0627 \u0641\u064a \u0627\u0644\u0645\u062d\u0627\u062f\u062b\u0629: " + "\u060c ".join(seen_products) + ".") if seen_products else "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0646\u062a\u062c\u0627\u062a \u0645\u0648\u062b\u0642\u0629 \u0638\u0647\u0631\u062a \u0641\u064a \u0647\u0630\u0647 \u0627\u0644\u0645\u062d\u0627\u062f\u062b\u0629 \u0628\u0639\u062f."
    if kind == "main_interest":
        focus = latest_products or seen_products[:2]
        if not focus:
            return None
        answer = "\u0627\u0647\u062a\u0645\u0627\u0645\u0647 \u0627\u0644\u0623\u0633\u0627\u0633\u064a \u0627\u0644\u0622\u0646 \u0647\u0648 " + "\u060c ".join(focus) + "."
        return answer + (" \u0648\u064a\u0648\u062c\u062f \u0627\u0639\u062a\u0631\u0627\u0636 \u0635\u0631\u064a\u062d \u0639\u0644\u0649 \u0627\u0644\u0633\u0639\u0631\u060c \u0648\u0647\u0648 \u0639\u0627\u0626\u0642 \u0642\u0631\u0627\u0631 \u0648\u0644\u064a\u0633 \u0627\u0647\u062a\u0645\u0627\u0645\u064b\u0627 \u0628\u062f\u064a\u0644\u064b\u0627." if "objection_price" in evidence_types else "")
    if kind == "important_notes":
        notes = []
        if seen_products:
            notes.append("\u0646\u0627\u0642\u0634 " + "\u060c ".join(seen_products[:3]))
        if "objection_price" in evidence_types:
            notes.append("\u0623\u0628\u062f\u0649 \u0627\u0639\u062a\u0631\u0627\u0636\u064b\u0627 \u0635\u0631\u064a\u062d\u064b\u0627 \u0639\u0644\u0649 \u0627\u0644\u0633\u0639\u0631")
        if "price_question" in evidence_types:
            notes.append("\u0637\u0644\u0628 \u062a\u0648\u0636\u064a\u062d \u0627\u0644\u0633\u0639\u0631")
        return ("\u0623\u0647\u0645 \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a: " + "\u061b ".join(notes) + ".") if notes else "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0644\u0627\u062d\u0638\u0627\u062a \u062a\u062c\u0627\u0631\u064a\u0629 \u0642\u0648\u064a\u0629 \u0645\u062b\u0628\u062a\u0629 \u0641\u064a \u0627\u0644\u0645\u062d\u0627\u062f\u062b\u0629 \u0628\u0639\u062f."

    criteria = _expressed_criteria(customer_messages)
    return ("\u0627\u0644\u0645\u0639\u0627\u064a\u064a\u0631 \u0627\u0644\u062a\u064a \u0638\u0647\u0631\u062a \u0645\u0646 \u0643\u0644\u0627\u0645 \u0627\u0644\u0639\u0645\u064a\u0644: " + "\u060c ".join(criteria) + ".") if criteria else "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0648\u0627\u0635\u0641\u0627\u062a \u0623\u0648 \u0645\u0639\u0627\u064a\u064a\u0631 \u0635\u0631\u0651\u062d \u0628\u0647\u0627 \u0627\u0644\u0639\u0645\u064a\u0644 \u0628\u0648\u0636\u0648\u062d \u0628\u0639\u062f\u061b \u0644\u0627 \u064a\u0646\u0628\u063a\u064a \u0627\u0641\u062a\u0631\u0627\u0636 \u0627\u062d\u062a\u064a\u0627\u062c \u063a\u064a\u0631 \u0645\u0630\u0643\u0648\u0631."
