import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import desc, func
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from database import CommercialEvent, Company, Lead, LeadEvidence, Message, WorkspaceSuggestedReply, get_phone_variants, normalize_whatsapp_number


PROJECTION_CLASSES = {
    "WAITING_ON_US",
    "READY_TO_CLOSE",
    "STUCK_ON_OBJECTION",
    "REGRESSING",
}

# A currently-processing message is not an incident. It becomes an explicit,
# deterministic recovery item only after this persisted age threshold.
PROCESSING_STUCK_AFTER_SECONDS = 120


def _owner_attention_copy(projection_class: str, lead_name: str, reason_code: str) -> Tuple[str, str, str, str]:
    waiting_reasons = {
        "HUMAN_TAKEOVER_ACTIVE": "المحادثة تحت تولٍّ بشري ولم يُرسل رد بعد آخر رسالة للعميل.",
        "AUTO_REPLY_DISABLED": "الرد الآلي معطل حاليًا، لذلك تحتاج هذه الرسالة متابعة يدوية.",
        "PROCESSING_FAILURE": "تعذر إكمال معالجة آخر رسالة ولم يُحفظ رد ظاهر للعميل.",
        "PROCESSING_STUCK": "آخر رسالة تجاوزت مهلة المعالجة المحددة ولم يظهر رد محفوظ حتى الآن.",
        "MANUAL_RESPONSE_PENDING": "يوجد رد مقترح يحتاج مراجعة وإرسالًا يدويًا.",
        "UNKNOWN_INCIDENT": "آخر رسالة للعميل ما زالت بلا رد، والسبب التشغيلي غير مثبت.",
    }
    if projection_class == "WAITING_ON_US":
        return (
            f"{lead_name} ينتظر ردًا",
            waiting_reasons.get(reason_code, "آخر رسالة للعميل لم تتلق ردًا بعد."),
            "آخر تطور هو رسالة عميل لم يتبعها رد ظاهر.",
            "افتح المحادثة وأرسل ردًا مناسبًا، أو راجع حالة المعالجة قبل إعادة المحاولة.",
        )
    if projection_class == "READY_TO_CLOSE":
        return (
            f"{lead_name} يظهر حركة شراء",
            "توجد إشارة موثقة لبدء الطلب أو الشراء أو الاستعجال؛ ليست مجرد تصفح عام.",
            "تجاوزت المحادثة مرحلة الاستكشاف إلى خطوة شراء أو متابعة محددة.",
            "أكد المنتج والكمية والخطوة التالية الموثقة فقط.",
        )
    if projection_class == "STUCK_ON_OBJECTION":
        return (
            f"{lead_name} لديه اعتراض على السعر",
            "العميل عبّر عن اعتراض سعري صريح. لا نفترض السبب ما لم يذكره.",
            "انتقلت المحادثة من الاستفسار إلى عائق قرار موثق.",
            "اعترف بالاعتراض، اشرح القيمة من حقائق موثقة، واسأل سؤال توضيح واحدًا عند الحاجة.",
        )
    return (
        f"{lead_name} يتراجع زخمه",
        "توجد إشارة تردد أو أن الحالة التجارية تشير إلى تراجع الزخم.",
        "تحولت المحادثة من تقدم إلى تأجيل أو إعادة نظر.",
        "خفف الضغط، عالج النقطة المحددة، واعرض خطوة بسيطة تالية.",
    )


def _safe_json(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lead_name(lead: Lead) -> str:
    return lead.name or lead.customer_provided_phone or lead.whatsapp_number or lead.phone or lead.external_customer_id or f"Lead {lead.id}"


def _lead_user_ids(lead: Lead) -> List[str]:
    values = set()
    for item in (lead.phone, lead.whatsapp_number, lead.whatsapp_jid, lead.customer_provided_phone):
        if item:
            values.add(item)
            values.update(get_phone_variants(normalize_whatsapp_number(item)))
    if lead.channel_type == "VELOR_WEB_CHAT" and lead.external_customer_id:
        values.add(lead.external_customer_id)
    return [value for value in values if value]


def _serialize_evidence(row: LeadEvidence) -> Dict[str, Any]:
    return {
        "type": row.evidence_type,
        "source_text": row.source_text,
        "normalized_value": row.normalized_value,
        "source_message_internal_id": row.message_internal_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_commercial_event(row: CommercialEvent) -> Dict[str, Any]:
    return {
        "type": row.event_type,
        "source_text": row.source_text,
        "normalized_value": row.product_ref,
        "source_message_internal_id": row.source_message_internal_id,
        "source_event_id": row.id,
        "created_at": row.observed_at.isoformat() if row.observed_at else None,
        "provenance": row.provenance,
    }


def _freshness(observed_at: Optional[datetime], now: datetime) -> Dict[str, Any]:
    observed = _as_utc(observed_at) or now
    age_seconds = max(0, int((now - observed).total_seconds()))
    if age_seconds <= 15 * 60:
        label = "fresh"
    elif age_seconds <= 24 * 60 * 60:
        label = "recent"
    else:
        label = "stale"
    return {
        "observed_at": observed.isoformat(),
        "age_seconds": age_seconds,
        "label": label,
    }


def _latest_message(db: Session, company_id: str, lead: Lead) -> Optional[Message]:
    ids = _lead_user_ids(lead)
    if not ids:
        return None
    return (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.user_id.in_(ids), Message.is_deleted == False)
        .order_by(desc(Message.created_at), desc(Message.id))
        .first()
    )


def _latest_outgoing_after(db: Session, company_id: str, lead: Lead, incoming: Message) -> Optional[Message]:
    ids = _lead_user_ids(lead)
    if not ids:
        return None
    return (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.user_id.in_(ids),
            Message.direction == "outgoing",
            Message.is_deleted == False,
            Message.created_at >= incoming.created_at,
        )
        .order_by(desc(Message.created_at), desc(Message.id))
        .first()
    )


def _active_suggestion(db: Session, company_id: str, lead_id: int, source_message_id: Optional[str]) -> Optional[WorkspaceSuggestedReply]:
    query = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company_id,
        WorkspaceSuggestedReply.lead_id == lead_id,
        WorkspaceSuggestedReply.status == "suggested",
    )
    if source_message_id:
        query = query.filter(WorkspaceSuggestedReply.source_message_internal_id == source_message_id)
    return query.order_by(desc(WorkspaceSuggestedReply.created_at)).first()


def _projection(
    *,
    projection_class: str,
    lead: Lead,
    what: str,
    why: str,
    what_changed: str,
    what_next: str,
    reason_code: str,
    freshness: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    score: int,
) -> Dict[str, Any]:
    score = max(1, min(100, int(score)))
    what, why, what_changed, what_next = _owner_attention_copy(projection_class, _lead_name(lead), reason_code)
    source_key = next(
        (
            str(row.get("source_message_internal_id") or row.get("source_event_id"))
            for row in evidence
            if row.get("source_message_internal_id") or row.get("source_event_id")
        ),
        str(freshness.get("observed_at") or "unknown"),
    )
    return {
        "id": f"{projection_class}:{lead.id}:{reason_code}:{source_key}",
        "projection_class": projection_class,
        "type": projection_class,
        "lead_id": lead.id,
        "lead_name": _lead_name(lead),
        "channel": lead.channel_type,
        "title": what,
        "what": what,
        "why": why,
        "what_changed": what_changed,
        "what_next": what_next,
        "evidence": evidence,
        "reason_code": reason_code,
        "freshness": freshness,
        "score": score,
        "priority_score": score,
        "status": "open",
        "created_at": freshness.get("observed_at"),
        "next_best_action": what_next,
        "why_summary": why,
        "suggested_action": what_next,
        "source_entities": {"lead_ids": [lead.id]},
        "data": {
            "customer": _lead_name(lead),
            "reason": why,
            "action_text": what_next,
            "priority": score,
            "projection_class": projection_class,
            "reason_code": reason_code,
        },
    }


def _waiting_projection(
    db: Session,
    company: Company,
    lead: Lead,
    rows: List[LeadEvidence],
    now: datetime,
    *,
    latest_message: Optional[Message] = None,
    latest_outgoing: Optional[Message] = None,
    active_suggestion: Optional[WorkspaceSuggestedReply] = None,
    prefetched: bool = False,
) -> Optional[Dict[str, Any]]:
    latest = latest_message if prefetched else _latest_message(db, company.company_id, lead)
    if not latest or latest.direction != "incoming" or latest.sender != "user":
        return None

    outgoing = latest_outgoing if prefetched else _latest_outgoing_after(db, company.company_id, lead, latest)
    if outgoing and outgoing.created_at >= latest.created_at:
        return None

    suggestion = active_suggestion if prefetched else _active_suggestion(db, company.company_id, lead.id, latest.internal_message_id)
    processing_status = latest.processing_status or "completed"

    reason_code: Optional[str] = None
    why = ""
    what_next = ""
    score = 70

    if lead.is_paused:
        reason_code = "HUMAN_TAKEOVER_ACTIVE"
        why = "The conversation is under human takeover and the latest customer message has no later owner reply."
        what_next = "Open the conversation and send the manual reply, or return VELOR to the conversation."
        score = 90
    elif getattr(company, "bot_auto_reply_enabled", True) is False:
        reason_code = "AUTO_REPLY_DISABLED"
        why = "Company auto-reply is disabled, so this customer cannot receive an automated answer."
        what_next = "Reply manually or re-enable auto-reply after reviewing the conversation."
        score = 88
    elif processing_status == "failed":
        reason_code = "PROCESSING_FAILURE"
        why = "The inbound message is marked failed by the processing claim and has no later reply."
        what_next = "Retry the customer turn or reply manually from the workspace."
        score = 92
    elif processing_status == "processing":
        processing_since = _as_utc(latest.processing_started_at) or _as_utc(latest.created_at) or now
        if (now - processing_since).total_seconds() < PROCESSING_STUCK_AFTER_SECONDS:
            return None
        reason_code = "PROCESSING_STUCK"
        why = "The customer turn exceeded the declared two-minute processing policy and no visible reply was persisted."
        what_next = "Retry the customer turn or take over and reply manually from the workspace."
        score = 82
    elif suggestion:
        reason_code = "MANUAL_RESPONSE_PENDING"
        why = "VELOR prepared a suggested reply for this customer turn, but it has not been sent."
        what_next = "Review the suggested reply, edit if needed, then send it manually."
        score = 78
    else:
        reason_code = "UNKNOWN_INCIDENT"
        why = "The latest customer message has no later reply even though no control gate explains the wait."
        what_next = "Inspect the conversation and either reply manually or investigate processing health."
        score = 75

    evidence = [_serialize_evidence(row) for row in rows[:3]]
    evidence.insert(
        0,
        {
            "type": "latest_customer_message",
            "source_text": latest.message,
            "normalized_value": None,
            "source_message_internal_id": latest.internal_message_id,
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        },
    )

    return _projection(
        projection_class="WAITING_ON_US",
        lead=lead,
        what=f"{_lead_name(lead)} needs a business reply",
        why=why,
        what_changed="The latest customer-authored message is still unanswered for a concrete operational reason.",
        what_next=what_next,
        reason_code=reason_code,
        freshness=_freshness(latest.created_at, now),
        evidence=evidence,
        score=score,
    )


def _prefetch_waiting_state(
    db: Session,
    company_id: str,
    leads: List[Lead],
) -> Tuple[Dict[int, Message], Dict[int, Message], Dict[int, WorkspaceSuggestedReply]]:
    """Load queue message/suggestion state in three bounded queries.

    The previous implementation issued up to three queries per lead.  Besides
    making the queue slow, that widened the time window in which rows from one
    refresh could describe different database snapshots.  Window functions
    keep the read count constant while retaining the existing newest-by-time
    semantics for every channel identifier owned by a lead.
    """
    ids_by_lead = {lead.id: _lead_user_ids(lead) for lead in leads}
    lead_by_user_id: Dict[str, int] = {}
    for lead_id, user_ids in ids_by_lead.items():
        for user_id in user_ids:
            # Identifiers are tenant-scoped.  If bad legacy data duplicated an
            # identifier, do not expose the same message through two customers.
            lead_by_user_id.setdefault(user_id, lead_id)
    user_ids = list(lead_by_user_id)
    if not user_ids:
        return {}, {}, {}

    def latest_rows(*, outgoing_only: bool) -> List[Message]:
        ranked = db.query(
            Message.id.label("message_id"),
            func.row_number().over(
                partition_by=Message.user_id,
                order_by=(Message.created_at.desc(), Message.id.desc()),
            ).label("row_number"),
        ).filter(
            Message.company_id == company_id,
            Message.user_id.in_(user_ids),
            Message.is_deleted == False,
        )
        if outgoing_only:
            ranked = ranked.filter(Message.direction == "outgoing")
        ranked = ranked.subquery()
        message_row = aliased(Message)
        return (
            db.query(message_row)
            .join(ranked, message_row.id == ranked.c.message_id)
            .filter(ranked.c.row_number == 1)
            .all()
        )

    latest_by_lead: Dict[int, Message] = {}
    for message in latest_rows(outgoing_only=False):
        lead_id = lead_by_user_id.get(message.user_id)
        current = latest_by_lead.get(lead_id)
        if lead_id is not None and (
            current is None
            or (message.created_at, message.id) > (current.created_at, current.id)
        ):
            latest_by_lead[lead_id] = message

    outgoing_by_lead: Dict[int, Message] = {}
    for message in latest_rows(outgoing_only=True):
        lead_id = lead_by_user_id.get(message.user_id)
        current = outgoing_by_lead.get(lead_id)
        if lead_id is not None and (
            current is None
            or (message.created_at, message.id) > (current.created_at, current.id)
        ):
            outgoing_by_lead[lead_id] = message

    source_ids = {
        message.internal_message_id
        for message in latest_by_lead.values()
        if message.direction == "incoming" and message.sender == "user"
    }
    suggestion_by_lead: Dict[int, WorkspaceSuggestedReply] = {}
    if source_ids:
        suggestions = (
            db.query(WorkspaceSuggestedReply)
            .filter(
                WorkspaceSuggestedReply.company_id == company_id,
                WorkspaceSuggestedReply.lead_id.in_(list(latest_by_lead)),
                WorkspaceSuggestedReply.source_message_internal_id.in_(source_ids),
                WorkspaceSuggestedReply.status == "suggested",
            )
            .order_by(desc(WorkspaceSuggestedReply.created_at), desc(WorkspaceSuggestedReply.id))
            .all()
        )
        for suggestion in suggestions:
            suggestion_by_lead.setdefault(suggestion.lead_id, suggestion)

    return latest_by_lead, outgoing_by_lead, suggestion_by_lead


def _ready_projection(
    lead: Lead,
    rows: List[LeadEvidence],
    sales_state: Dict[str, Any],
    event_rows: List[CommercialEvent],
    now: datetime,
) -> Optional[Dict[str, Any]]:
    evidence_types = {row.evidence_type for row in rows}
    intents = set(sales_state.get("buyer_intents") or [])
    primary = sales_state.get("primary_state")

    purchase_types = {"PURCHASE_EXECUTION_REQUEST", "PURCHASE_COMMITMENT", "PURCHASE_INTENT_EXPRESSED"}
    state_types = purchase_types | {"OBJECTION_EXPRESSED", "CONVERSATION_STALLED", "CONFIRMED_ORDER", "PAID"}
    latest_state_event = next((row for row in event_rows if row.event_type in state_types), None)
    purchase_events = [latest_state_event] if latest_state_event and latest_state_event.event_type in purchase_types else []
    if latest_state_event and latest_state_event.event_type in {
        "OBJECTION_EXPRESSED", "CONVERSATION_STALLED", "CONFIRMED_ORDER", "PAID"
    }:
        return None
    explicit_ready = bool(evidence_types & {"start_intent", "buying_signal", "urgency"})
    canonical_ready = bool(purchase_events) or primary in {"READY_TO_BUY", "COMMITTING"} or bool(intents & {"PURCHASE_COMMITMENT", "PAYMENT_INQUIRY"})
    if not explicit_ready and not canonical_ready:
        return None

    relevant_events = sorted(purchase_events, key=lambda row: (_as_utc(row.observed_at) or now, row.id), reverse=True)
    source_event = relevant_events[0] if relevant_events else None
    relevant = [row for row in rows if row.evidence_type in {"start_intent", "buying_signal", "urgency", "price_question"}][:4]
    observed = source_event.observed_at if source_event else (relevant[0].created_at if relevant else lead.updated_at)
    if source_event:
        reason = source_event.event_type
    elif "PURCHASE_COMMITMENT" in intents or primary == "COMMITTING":
        reason = "PURCHASE_COMMITMENT"
    elif "PAYMENT_INQUIRY" in intents:
        reason = "PAYMENT_INQUIRY"
    elif "start_intent" in evidence_types:
        reason = "START_INTENT"
    else:
        reason = "BUYING_SIGNAL"
    score_by_reason = {
        "PURCHASE_EXECUTION_REQUEST": 94,
        "PURCHASE_COMMITMENT": 90,
        "PAYMENT_INQUIRY": 88,
        "PURCHASE_INTENT_EXPRESSED": 86,
        "START_INTENT": 84,
        "BUYING_SIGNAL": 78,
    }
    return _projection(
        projection_class="READY_TO_CLOSE",
        lead=lead,
        what=f"{_lead_name(lead)} is showing purchase motion",
        why="The customer provided explicit start, buying, urgency, or purchase-step evidence. This is not inferred from a generic browse.",
        what_changed="The conversation moved beyond discovery into a documented buying or next-step signal.",
        what_next="Confirm the requested product, quantity, and trusted next step without inventing payment or discount terms.",
        reason_code=reason,
        freshness=_freshness(observed, now),
        evidence=([_serialize_commercial_event(source_event)] if source_event else []) + [_serialize_evidence(row) for row in relevant],
        score=score_by_reason.get(reason, 78),
    )


def _objection_projection(
    lead: Lead,
    rows: List[LeadEvidence],
    sales_state: Dict[str, Any],
    event_rows: List[CommercialEvent],
    now: datetime,
) -> Optional[Dict[str, Any]]:
    evidence_types = {row.evidence_type for row in rows}
    intents = set(sales_state.get("buyer_intents") or [])
    primary = sales_state.get("primary_state")
    objection_event = next((row for row in event_rows if row.event_type == "OBJECTION_EXPRESSED"), None)
    if not objection_event and "objection_price" not in evidence_types and primary not in {"OBJECTING", "NEGOTIATING"} and "PRICE_OBJECTION" not in intents:
        return None

    relevant = [row for row in rows if row.evidence_type in {"objection_price", "price_question", "product_mention"}][:4]
    observed = objection_event.observed_at if objection_event else (relevant[0].created_at if relevant else lead.updated_at)
    return _projection(
        projection_class="STUCK_ON_OBJECTION",
        lead=lead,
        what=f"{_lead_name(lead)} is blocked on a price concern",
        why="There is explicit objection evidence. No root cause is assumed unless the customer stated it.",
        what_changed="The conversation shifted from asking or browsing into a documented objection that can block purchase.",
        what_next="Acknowledge the concern, use only trusted product/value facts, and ask one clarifying question if the reason is still unknown.",
        reason_code="PRICE_OBJECTION_PRESENT",
        freshness=_freshness(observed, now),
        evidence=([_serialize_commercial_event(objection_event)] if objection_event else []) + [_serialize_evidence(row) for row in relevant],
        score=84,
    )


def _regressing_projection(
    lead: Lead,
    rows: List[LeadEvidence],
    sales_state: Dict[str, Any],
    event_rows: List[CommercialEvent],
    now: datetime,
) -> Optional[Dict[str, Any]]:
    evidence_types = {row.evidence_type for row in rows}
    momentum = sales_state.get("momentum")
    stalled_event = next((row for row in event_rows if row.event_type == "CONVERSATION_STALLED"), None)
    if not stalled_event and "hesitation" not in evidence_types and momentum != "REGRESSING":
        return None

    relevant = [row for row in rows if row.evidence_type in {"hesitation", "objection_price"}][:4]
    observed = stalled_event.observed_at if stalled_event else (relevant[0].created_at if relevant else lead.updated_at)
    return _projection(
        projection_class="REGRESSING",
        lead=lead,
        what=f"{_lead_name(lead)} is losing momentum",
        why="The customer introduced hesitation or the canonical sales state marks momentum as regressing.",
        what_changed="The customer moved away from forward motion toward delay, reconsideration, or lower commitment.",
        what_next="Reduce pressure, answer the specific concern with evidence, and offer a simple next step or follow-up.",
        reason_code="CONVERSATION_STALLED" if stalled_event else ("REGRESSING_MOMENTUM" if momentum == "REGRESSING" else "HESITATION_SIGNAL"),
        freshness=_freshness(observed, now),
        evidence=([_serialize_commercial_event(stalled_event)] if stalled_event else []) + [_serialize_evidence(row) for row in relevant],
        score=72,
    )


def _sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
    freshness = item.get("freshness") or {}
    observed = freshness.get("observed_at") or ""
    try:
        ts = datetime.fromisoformat(observed.replace("Z", "+00:00")).timestamp()
    except Exception:
        ts = 0
    reason_rank = {
        "PROCESSING_FAILURE": 0,
        "PROCESSING_STUCK": 1,
        "HUMAN_TAKEOVER_ACTIVE": 1,
        "PURCHASE_EXECUTION_REQUEST": 2,
        "PURCHASE_COMMITMENT": 3,
        "PAYMENT_INQUIRY": 4,
        "PURCHASE_INTENT_EXPRESSED": 4,
        "START_INTENT": 4,
        "BUYING_SIGNAL": 4,
        "PRICE_OBJECTION_PRESENT": 5,
        "CONVERSATION_STALLED": 6,
        "REGRESSING_MOMENTUM": 6,
        "HESITATION_SIGNAL": 6,
    }
    class_rank = reason_rank.get(item.get("reason_code"), {
        "WAITING_ON_US": 0,
        "READY_TO_CLOSE": 4,
        "STUCK_ON_OBJECTION": 5,
        "REGRESSING": 6,
    }.get(item.get("projection_class"), 9))
    return (class_rank, -(item.get("score") or 0), -ts, item.get("lead_id") or 0)


def get_owner_attention_projection(db: Session, company_id: str, limit: int = 5) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company:
        return {
            "success": True,
            "items": [],
            "attention": [],
            "generated_at": now.isoformat(),
            "classes": sorted(PROJECTION_CLASSES),
            "message": "Company was not found.",
        }

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
        .limit(200)
        .all()
    )
    grouped: Dict[int, List[LeadEvidence]] = defaultdict(list)
    for row in evidence_rows:
        grouped[row.lead_id].append(row)

    lead_ids = set(grouped.keys())
    recent_message_leads = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
            Lead.stage.notin_(["Won", "Lost"]),
        )
        .order_by(desc(Lead.updated_at))
        .limit(100)
        .all()
    )
    for lead in recent_message_leads:
        lead_ids.add(lead.id)

    leads_by_id = {lead.id: lead for lead in recent_message_leads}
    missing_lead_ids = lead_ids - set(leads_by_id)
    if missing_lead_ids:
        extra_leads = db.query(Lead).filter(
            Lead.company_id == company_id,
            Lead.id.in_(list(missing_lead_ids)),
            Lead.is_deleted == False,
            Lead.is_test == False,
            Lead.stage.notin_(["Won", "Lost"]),
        ).all()
        leads_by_id.update({lead.id: lead for lead in extra_leads})
    leads = list(leads_by_id.values())

    commercial_rows = (
        db.query(CommercialEvent)
        .filter(
            CommercialEvent.company_id == company_id,
            CommercialEvent.lead_id.in_([lead.id for lead in leads]),
        )
        .order_by(desc(CommercialEvent.observed_at), desc(CommercialEvent.id))
        .limit(300)
        .all()
        if leads
        else []
    )
    commercial_by_lead: Dict[int, List[CommercialEvent]] = defaultdict(list)
    for row in commercial_rows:
        commercial_by_lead[row.lead_id].append(row)

    latest_by_lead, outgoing_by_lead, suggestion_by_lead = _prefetch_waiting_state(
        db, company_id, leads
    )

    items: List[Dict[str, Any]] = []
    for lead in leads:
        rows = grouped.get(lead.id, [])
        event_rows = commercial_by_lead.get(lead.id, [])
        sales_state = _safe_json(getattr(lead, "sales_state_snapshot", None), {})
        for candidate in (
            _waiting_projection(
                db,
                company,
                lead,
                rows,
                now,
                latest_message=latest_by_lead.get(lead.id),
                latest_outgoing=outgoing_by_lead.get(lead.id),
                active_suggestion=suggestion_by_lead.get(lead.id),
                prefetched=True,
            ),
            _ready_projection(lead, rows, sales_state, event_rows, now),
            _objection_projection(lead, rows, sales_state, event_rows, now),
            _regressing_projection(lead, rows, sales_state, event_rows, now),
        ):
            if candidate:
                items.append(candidate)

    # Keep the source projection API class-complete for existing consumers.
    # The dashboard queue applies its stronger one-action-per-lead grouping in
    # ``get_commercial_queue`` below.
    deduped: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for item in items:
        key = (item["lead_id"], item["projection_class"])
        current = deduped.get(key)
        if current is None or _sort_key(item) < _sort_key(current):
            deduped[key] = item

    # The previous hard cap of 10 silently under-counted the owner-attention KPI
    # and also made get_commercial_queue(limit=25) return at most 10 records.
    # Keep the scan bounded by the 100 eligible recent leads above while honoring
    # the caller's requested queue size.
    final_items = sorted(deduped.values(), key=_sort_key)[: max(1, min(int(limit or 5), 100))]
    return {
        "success": True,
        "items": final_items,
        "attention": final_items,
        "generated_at": now.isoformat(),
        "classes": sorted(PROJECTION_CLASSES),
        "message": "" if final_items else "No launch attention items have enough evidence right now.",
    }


def get_commercial_queue(db: Session, company_id: str, limit: int = 25) -> Dict[str, Any]:
    """Compact normalized queue: one highest-priority active item per lead."""
    from services.follow_up_service import list_follow_ups

    now = datetime.now(timezone.utc)
    projection = get_owner_attention_projection(db, company_id, limit=100)
    category_map = {
        "WAITING_ON_US": "WAITING_ON_US",
        "READY_TO_CLOSE": "READY_FOR_PURCHASE_STEP",
        "STUCK_ON_OBJECTION": "AT_RISK",
        "REGRESSING": "AT_RISK",
    }
    legacy_status = {
        "WAITING_ON_US": "NEEDS_ACTION",
        "READY_FOR_PURCHASE_STEP": "PURCHASE_HANDOFF",
        "AT_RISK": "NEEDS_ACTION",
        "FOLLOW_UP_DUE": "FOLLOW_UP",
    }
    category_labels = {
        "WAITING_ON_US": "ينتظر ردنا",
        "READY_FOR_PURCHASE_STEP": "جاهز لخطوة الشراء",
        "AT_RISK": "يحتاج معالجة مخاطرة موثقة",
        "FOLLOW_UP_DUE": "موعد متابعة مستحق",
    }

    candidates: List[Dict[str, Any]] = []
    for item in projection.get("items", []):
        evidence = item.get("evidence") or []
        latest = evidence[0] if evidence else {}
        product = next(
            (row.get("normalized_value") for row in evidence if row.get("type") == "product_mention" and row.get("normalized_value")),
            None,
        )
        category = category_map.get(item.get("projection_class"), "AT_RISK")
        freshness = item.get("freshness") or {}
        queue_id = f"recovery:{item.get('id')}"
        candidates.append({
            "queue_item_id": queue_id,
            "id": queue_id,
            "lead_id": item.get("lead_id"),
            "display_label": item.get("lead_name") or f"زائر {item.get('lead_id')}",
            "category": category,
            "category_label": category_labels[category],
            "reason_code": item.get("reason_code"),
            "reason": item.get("why"),
            "source_message_internal_id": latest.get("source_message_internal_id"),
            "source_message_id": latest.get("source_message_internal_id"),
            "source_event_id": latest.get("source_event_id"),
            "detected_at": freshness.get("observed_at"),
            "age_seconds": freshness.get("age_seconds"),
            "freshness": freshness.get("label"),
            "evidence": evidence[:5],
            "missing_information": [],
            "recommended_action": item.get("what_next"),
            "due_at": None,
            "status": legacy_status[category],
            "status_label": category_labels[category],
            "task_status": "open",
            "channel": item.get("channel") or "conversation",
            "workspace_path": f"/inbox/{item.get('lead_id')}",
            "current_product": product,
            "latest_message": (latest.get("source_text") or "")[:180] or None,
            "waiting_duration": freshness.get("label"),
            "priority_category": "عاجل" if (item.get("score") or 0) >= 85 else "يحتاج متابعة",
            "case_detail": {
                "issue": item.get("what"),
                "reason": item.get("why"),
                "evidence": [{"label": row.get("type"), "message_id": row.get("source_message_internal_id")} for row in evidence[:3]],
                "missing_information": [],
                "primary_action": item.get("what_next"),
            },
            "_sort": _sort_key(item),
        })

    for task in list_follow_ups(db, company_id, due_only=True, limit=100):
        detected = _as_utc(task.created_at) or now
        due_at = _as_utc(task.due_at)
        age_seconds = max(0, int((now - detected).total_seconds()))
        queue_id = f"follow-up:{task.id}:{task.source_identifier}"
        candidates.append({
            "queue_item_id": queue_id,
            "id": queue_id,
            "lead_id": task.lead_id,
            "display_label": (task.lead.name if task.lead else None) or f"زائر {task.lead_id}",
            "category": "FOLLOW_UP_DUE",
            "category_label": category_labels["FOLLOW_UP_DUE"],
            "reason_code": task.reason_code,
            "reason": task.explanation,
            "source_message_internal_id": task.source_message_internal_id,
            "source_message_id": task.source_message_internal_id,
            "source_event_id": task.source_event_id,
            "detected_at": detected.isoformat(),
            "age_seconds": age_seconds,
            "freshness": "fresh" if age_seconds <= 900 else ("recent" if age_seconds <= 86400 else "stale"),
            "evidence": ([{
                "type": "follow_up_source",
                "source_message_internal_id": task.source_message_internal_id,
                "source_event_id": task.source_event_id,
                "created_at": detected.isoformat(),
            }] if task.source_message_internal_id or task.source_event_id else []),
            "missing_information": [],
            "recommended_action": "افتح المحادثة ونفّذ المتابعة الموثقة أو حدّث حالتها.",
            "due_at": due_at.isoformat() if due_at else None,
            "status": legacy_status["FOLLOW_UP_DUE"],
            "status_label": category_labels["FOLLOW_UP_DUE"],
            "task_status": task.status,
            "follow_up_task_id": task.id,
            "channel": getattr(task.lead, "channel_type", None),
            "workspace_path": f"/inbox/{task.lead_id}",
            "current_product": None,
            "latest_message": None,
            "waiting_duration": "due",
            "priority_category": "متابعة مستحقة",
            "case_detail": {
                "issue": category_labels["FOLLOW_UP_DUE"],
                "reason": task.explanation,
                "evidence": [],
                "missing_information": [],
                "primary_action": "افتح المحادثة ونفّذ المتابعة الموثقة أو حدّث حالتها.",
            },
            "_sort": (7, -int(task.priority or 0), due_at.timestamp() if due_at else 0, task.lead_id),
        })

    current_by_lead: Dict[int, Dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda row: row["_sort"]):
        current_by_lead.setdefault(candidate["lead_id"], candidate)
    items = list(current_by_lead.values())[: max(1, min(int(limit or 25), 100))]
    for item in items:
        item.pop("_sort", None)
    return {
        "state": "HAS_ACTIONS" if items else "NO_ACTION_REQUIRED",
        "items": items,
        "sections": {
            key: [item for item in items if item["status"] == key]
            for key in ("NEEDS_ACTION", "PURCHASE_HANDOFF", "FOLLOW_UP", "WAITING_FOR_CUSTOMER", "RESOLVED")
        },
        "generated_at": projection.get("generated_at"),
    }
