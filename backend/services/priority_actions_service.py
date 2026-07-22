import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import Lead, LeadEvidence, Message, WorkspaceSuggestedReply, get_phone_variants, normalize_whatsapp_number


EVIDENCE_WEIGHTS = {
    "urgency": 40,
    "start_intent": 35,
    "buying_signal": 30,
    "price_question": 20,
    "objection_price": 20,
    "hesitation": 10,
    "product_mention": 10,
}

EVIDENCE_LABELS = {
    "urgency": "طلب ردًا سريعًا",
    "start_intent": "سأل عن بدء الطلب",
    "buying_signal": "أظهر اهتمامًا بالشراء",
    "price_question": "سأل عن السعر",
    "objection_price": "اعترض على السعر",
    "hesitation": "أظهر ترددًا",
    "product_mention": "ذكر منتجًا",
}


def _safe_json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _lead_name(lead: Lead) -> str:
    return lead.name or lead.phone or lead.whatsapp_number or f"Lead {lead.id}"


def _lead_user_ids(lead: Lead) -> List[str]:
    values = set()
    for item in (lead.phone, lead.whatsapp_number, lead.whatsapp_jid):
        if item:
            values.add(item)
            values.update(get_phone_variants(normalize_whatsapp_number(item)))
    return [value for value in values if value]


def _serialize_evidence(row: LeadEvidence) -> Dict[str, Any]:
    return {
        "type": row.evidence_type,
        "source_text": row.source_text,
        "normalized_value": row.normalized_value,
        "source_message_internal_id": row.message_internal_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "confidence": row.confidence,
    }


def _active_suggestion(db: Session, company_id: str, lead_id: int) -> Optional[WorkspaceSuggestedReply]:
    return (
        db.query(WorkspaceSuggestedReply)
        .filter(
            WorkspaceSuggestedReply.company_id == company_id,
            WorkspaceSuggestedReply.lead_id == lead_id,
            WorkspaceSuggestedReply.status == "suggested",
        )
        .order_by(desc(WorkspaceSuggestedReply.created_at))
        .first()
    )


def _latest_message_state(db: Session, company_id: str, lead: Lead) -> Tuple[Optional[Message], bool]:
    ids = _lead_user_ids(lead)
    if not ids:
        return None, False
    latest = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.user_id.in_(ids))
        .order_by(desc(Message.created_at))
        .first()
    )
    return latest, bool(latest and latest.sender == "user")


def _format_price(value: Any, currency: Optional[str]) -> str:
    try:
        text = f"{float(value):g}"
    except (TypeError, ValueError):
        return ""
    return f"{text} {currency}".strip() if currency else text


def _price_context_from_evidence(evidence_rows: List[LeadEvidence]) -> Tuple[Optional[str], Optional[str], List[str]]:
    product_row = next((row for row in evidence_rows if row.evidence_type == "product_mention"), None)
    if not product_row:
        return None, None, ["product", "price"]

    metadata = _safe_json_loads(product_row.metadata_json, {})
    product = metadata.get("matched_product_name") or product_row.normalized_value
    price = metadata.get("known_price")
    currency = metadata.get("currency")

    missing = []
    if not product:
        missing.append("product")
    if price is None:
        missing.append("price")
    if price is not None and not currency:
        missing.append("currency")

    return product, _format_price(price, currency) if price is not None else None, missing


def _build_suggested_reply(action_type: str, lead: Lead, evidence_rows: List[LeadEvidence], suggestion: Optional[WorkspaceSuggestedReply]) -> Optional[str]:
    product, price_text, missing = _price_context_from_evidence(evidence_rows)
    evidence_types = {row.evidence_type for row in evidence_rows}

    if action_type == "answer_price_question" and product and price_text:
        return f"تمام، سعر {product} هو {price_text}. ممكن تقول لي الكمية المطلوبة عشان أأكد لك التفاصيل النهائية؟"
    if action_type == "answer_price_question":
        return "ممكن تحدد المنتج والكمية المطلوبة؟ أحب أأكد لك السعر الصحيح بدون أي تخمين."
    if action_type == "handle_price_objection":
        return "فاهم إن السعر مهم. ممكن أعرف المنتج والكمية المطلوبة عشان أوضح لك أفضل قيمة مناسبة بدون ما أديك معلومة غير مؤكدة؟"
    if "start_intent" in evidence_types or "buying_signal" in evidence_types:
        return "تمام، أقدر أساعدك في الخطوة التالية. ممكن تحدد المنتج أو الكمية المطلوبة؟"
    return None


def _build_safe_suggested_reply(action_type: str, evidence_rows: List[LeadEvidence]) -> str:
    # Stored workspace suggestions can contain stale or ungrounded generated claims.
    # Priority Actions regenerates visible replies from current evidence only.
    product, price_text, _missing = _price_context_from_evidence(evidence_rows)
    evidence_types = {row.evidence_type for row in evidence_rows}

    if action_type == "answer_price_question" and product and price_text:
        return f"السعر الموثق لـ {product} هو {price_text}. ما الكمية المطلوبة حتى أؤكد التفاصيل النهائية؟"
    if action_type == "answer_price_question":
        return "هل يمكنك تأكيد المنتج والكمية المطلوبة؟ أريد أن أقدم السعر الصحيح دون تخمين."
    if action_type == "clarify_missing_data":
        return "هل يمكنك تأكيد المنتج أو الكمية المطلوبة حتى أجيب بدقة دون تخمين؟"
    if action_type == "handle_price_objection":
        return "أتفهم أن السعر مهم. هل يمكنك تأكيد المنتج والكمية حتى أوضح القيمة المناسبة دون تقديم عرض غير موثق؟"
    if action_type == "urgent_customer_waiting":
        return "شكرًا لانتظارك. يمكنني المساعدة، لكن أحتاج تأكيد التفاصيل الناقصة قبل تقديم إجابة دقيقة."
    if action_type == "resume_or_review_takeover":
        return "يمكنني المساعدة في الخطوة التالية. يرجى تأكيد أي تفاصيل ناقصة حتى أجيب بدقة."
    if "start_intent" in evidence_types or "buying_signal" in evidence_types:
        return "يمكنني المساعدة في الخطوة التالية. هل يمكنك تأكيد المنتج أو الكمية المطلوبة؟"
    return "يمكنني المساعدة. هل يمكنك تأكيد التفاصيل الناقصة حتى أجيب بدقة؟"


def _missing_data_for_action(action_type: str, evidence_rows: List[LeadEvidence], suggestion: Optional[WorkspaceSuggestedReply]) -> List[str]:
    missing = set()
    if suggestion:
        for item in _safe_json_loads(suggestion.missing_data, []):
            missing.add(item)

    evidence_types = {row.evidence_type for row in evidence_rows}
    product, price_text, price_missing = _price_context_from_evidence(evidence_rows)

    if action_type in {"answer_price_question", "clarify_missing_data", "follow_up_hot_lead"}:
        if "price_question" in evidence_types:
            missing.add("quantity")
        for item in price_missing:
            if item in {"product", "price", "currency"}:
                missing.add(item)
    if action_type == "handle_price_objection":
        if not product:
            missing.add("product")
        missing.add("quantity")

    return sorted(missing)


def _choose_action_type(lead: Lead, evidence_rows: List[LeadEvidence], has_active_suggestion: bool, latest_customer_waiting: bool) -> str:
    types = {row.evidence_type for row in evidence_rows}
    if lead.is_paused and has_active_suggestion and latest_customer_waiting:
        return "resume_or_review_takeover"
    if "urgency" in types and latest_customer_waiting:
        return "urgent_customer_waiting"
    if "objection_price" in types:
        return "handle_price_objection"
    if "price_question" in types:
        product, price_text, missing = _price_context_from_evidence(evidence_rows)
        if product or price_text:
            return "answer_price_question"
        return "clarify_missing_data"
    if "start_intent" in types or "buying_signal" in types:
        return "follow_up_hot_lead"
    return "clarify_missing_data"


def _action_title(action_type: str, lead: Lead) -> str:
    name = _lead_name(lead)
    titles = {
        "follow_up_hot_lead": f"تابع {name} الآن",
        "answer_price_question": f"أجب على سؤال السعر من {name}",
        "handle_price_objection": f"عالج اعتراض السعر لدى {name}",
        "clarify_missing_data": f"اطلب بيانات ناقصة من {name}",
        "resume_or_review_takeover": f"راجع رد {name} المقترح",
        "urgent_customer_waiting": f"رد على {name} بشكل عاجل",
    }
    return titles.get(action_type, f"راجع {name}")


def _description(action_type: str, evidence_rows: List[LeadEvidence], latest_customer_waiting: bool) -> str:
    types = [row.evidence_type for row in evidence_rows[:4]]
    waiting_text = " وآخر رسالة من العميل تنتظر الرد." if latest_customer_waiting else "."
    labels = [EVIDENCE_LABELS.get(item, "إشارة موثقة من المحادثة") for item in types]
    return f"الأولوية مبنية على أدلة موثقة: {', '.join(labels)}{waiting_text}"


def _suggested_action(action_type: str, missing_data: List[str]) -> str:
    if action_type == "resume_or_review_takeover":
        return "افتح المحادثة وراجع الرد المقترح ثم أرسله يدويا إذا كان مناسبا."
    if action_type == "urgent_customer_waiting":
        return "افتح المحادثة ورد يدويا الآن، مع طلب أي بيانات ناقصة."
    if action_type == "answer_price_question":
        return "افتح المحادثة وأجب بسعر موثوق فقط، ثم اطلب الكمية إذا كانت ناقصة."
    if action_type == "handle_price_objection":
        return "استخدم ردا يوضح القيمة واسأل عن المنتج والكمية بدلا من عرض خصم غير موثق."
    if missing_data:
        return f"افتح المحادثة واطلب: {', '.join(missing_data)}."
    return "افتح المحادثة وحدد الخطوة التالية يدويا."


def _base_score(evidence_rows: List[LeadEvidence]) -> int:
    found = {row.evidence_type for row in evidence_rows}
    return sum(EVIDENCE_WEIGHTS.get(kind, 0) for kind in found)


def _action_from_lead(db: Session, company_id: str, lead: Lead, evidence_rows: List[LeadEvidence], now: datetime) -> Optional[Dict[str, Any]]:
    if not evidence_rows:
        return None

    latest_message, latest_customer_waiting = _latest_message_state(db, company_id, lead)
    suggestion = _active_suggestion(db, company_id, lead.id)
    action_type = _choose_action_type(lead, evidence_rows, bool(suggestion), latest_customer_waiting)
    missing = _missing_data_for_action(action_type, evidence_rows, suggestion)

    score = _base_score(evidence_rows)
    if suggestion:
        score += 15
    if latest_customer_waiting:
        score += 20
    product, price_text, _price_missing = _price_context_from_evidence(evidence_rows)
    if product and price_text:
        score += 10
    if missing:
        score -= 5
    score = max(1, min(100, score))

    confidence_values = [row.confidence or 0 for row in evidence_rows]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.4
    if missing:
        confidence = min(confidence, 0.82)

    suggested_reply = _build_safe_suggested_reply(action_type, evidence_rows)
    action_id = f"{action_type}:{lead.id}:{evidence_rows[0].message_internal_id}"
    created_at = evidence_rows[0].created_at or now
    evidence = [_serialize_evidence(row) for row in evidence_rows[:5]]

    action = {
        "id": action_id,
        "type": action_type,
        "title": _action_title(action_type, lead),
        "description": _description(action_type, evidence_rows, latest_customer_waiting),
        "lead_id": lead.id,
        "lead_name": _lead_name(lead),
        "score": score,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "evidence": evidence,
        "missing_data": missing,
        "suggested_action": _suggested_action(action_type, missing),
        "suggested_reply": suggested_reply,
        "status": "open",
        "created_at": created_at.isoformat() if created_at else now.isoformat(),
        "source_entities": {
            "lead_ids": [lead.id],
            "product_names": sorted({row.normalized_value for row in evidence_rows if row.evidence_type == "product_mention" and row.normalized_value}),
        },
        "data": {
            "customer": _lead_name(lead),
            "reason": _description(action_type, evidence_rows, latest_customer_waiting),
            "action_text": "افتح المحادثة",
            "priority": score,
        },
    }
    if latest_message and latest_customer_waiting:
        action["data"]["waiting_time"] = "بانتظار الرد"
    return action


def _action_sort_key(action: Dict[str, Any]) -> Tuple[Any, ...]:
    try:
        created_at = datetime.fromisoformat(action.get("created_at") or "")
        timestamp = created_at.timestamp()
    except Exception:
        timestamp = 0.0
    return (
        -(action.get("score") or 0),
        -timestamp,
        action.get("lead_id") or 0,
        action.get("type") or "",
        action.get("id") or "",
    )


def get_priority_actions(db: Session, company_id: str, limit: int = 5) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    eligible_lead_ids = db.query(Lead.id).filter(
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    )
    evidence_rows = (
        db.query(LeadEvidence)
        .filter(
            LeadEvidence.company_id == company_id,
            LeadEvidence.lead_id != None,
            LeadEvidence.lead_id.in_(eligible_lead_ids),
        )
        .order_by(desc(LeadEvidence.created_at))
        .limit(150)
        .all()
    )

    grouped: Dict[int, List[LeadEvidence]] = defaultdict(list)
    for row in evidence_rows:
        if row.evidence_type in EVIDENCE_WEIGHTS:
            grouped[row.lead_id].append(row)

    if not grouped:
        return {
            "success": True,
            "actions": [],
            "priorities": [],
            "message": "لا توجد أدلة كافية لبناء قائمة إجراءات ذات أولوية.",
            "generated_at": now.isoformat(),
        }

    lead_ids = list(grouped.keys())
    leads = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.id.in_(lead_ids),
            Lead.is_deleted == False,
            Lead.is_test == False,
            Lead.stage.notin_(["Won", "Lost"]),
        )
        .all()
    )
    leads_by_id = {lead.id: lead for lead in leads}

    actions = []
    for lead_id, rows in grouped.items():
        lead = leads_by_id.get(lead_id)
        if not lead:
            continue
        action = _action_from_lead(db, company_id, lead, rows, now)
        if action:
            actions.append(action)

    actions.sort(key=_action_sort_key)
    actions = actions[: max(1, min(limit, 5))]
    return {
        "success": True,
        "actions": actions,
        "priorities": actions,
        "message": "" if actions else "لا توجد أدلة كافية لبناء قائمة إجراءات ذات أولوية.",
        "generated_at": now.isoformat(),
    }
