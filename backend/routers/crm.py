from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timezone
from sqlalchemy import desc
from sqlalchemy.orm import Session
from database import (
    get_db,
    Lead,
    CustomerNote,
    ActivityLog,
    Message,
    LeadEvidence,
    Company,
    WorkspaceSuggestedReply,
    normalize_whatsapp_number,
    get_phone_variants,
)
from routers.auth import get_current_user
from pydantic import BaseModel
from utils import repair_mojibake
import logging
import json
from services.customer_interpreter import interpret_customer_conversation, render_customer_brief
from services.product_context_service import get_company_products

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/crm", tags=["CRM"])


class SuggestionStatusUpdate(BaseModel):
    status: str


def _serialize_workspace_suggestion(suggestion: WorkspaceSuggestedReply) -> dict:
    try:
        missing_data = json.loads(suggestion.missing_data or "[]")
    except json.JSONDecodeError:
        missing_data = []
    try:
        fact_ids_used = json.loads(getattr(suggestion, "fact_ids_used", None) or "[]")
    except json.JSONDecodeError:
        fact_ids_used = []
    try:
        variants = json.loads(getattr(suggestion, "variants_json", None) or "[]")
    except json.JSONDecodeError:
        variants = []
    if not variants:
        variants = [{
            "style": getattr(suggestion, "style", None) or "natural",
            "label": "طبيعي",
            "text": suggestion.suggested_reply,
            "fact_ids_used": fact_ids_used,
        }]

    return {
        "id": suggestion.id,
        "lead_id": suggestion.lead_id,
        "company_id": suggestion.company_id,
        "source_message_id": suggestion.source_message_id,
        "source_message_internal_id": suggestion.source_message_internal_id,
        "suggested_reply": suggestion.suggested_reply,
        "why_this_reply": suggestion.why_this_reply,
        "evidence_summary": suggestion.evidence_summary,
        "missing_data": missing_data,
        "confidence": suggestion.confidence,
        "status": suggestion.status,
        "created_at": _iso_utc(suggestion.created_at),
        "style": getattr(suggestion, "style", None) or "natural",
        "answers_message_id": suggestion.source_message_id,
        "fact_ids_used": fact_ids_used,
        "variants": variants,
        "generated_at": _iso_utc(suggestion.created_at),
        "context_version": getattr(suggestion, "context_version", None) or "v2",
        "stale_status": suggestion.status == "stale",
        "stale_reason": getattr(suggestion, "stale_reason", None),
    }


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_json_loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


_INTERNAL_SUMMARY_MARKERS = (
    "fallback analysis", "intent score", "customer message preserved",
    "summary:", "raw model output", "raw snapshot output", "v2 trace path",
)


def _merchant_facing_summary(lead) -> str:
    """Keep engineering diagnostics and speculative snapshots out of the CRM."""
    candidate = repair_mojibake(lead.ai_summary or "").strip()
    if candidate and not any(marker in candidate.casefold() for marker in _INTERNAL_SUMMARY_MARKERS):
        return candidate[:220]
    product = repair_mojibake(lead.interest or "").strip()
    latest = repair_mojibake(lead.last_message_preview or lead.last_message or "").strip()
    if product and latest:
        return f"يسأل عن {product}."
    if product:
        return f"يهتم بـ{product}."
    if latest:
        return "وصلت رسالة جديدة وتحتاج مراجعة." 
    return "لا توجد معلومات كافية لتحديد اهتمامه بعد."


def _merchant_display_name(lead) -> str:
    name = repair_mojibake(lead.name or "").strip()
    if name and name not in {"عميل محتمل", "Unknown", "غير معروف"}:
        return name
    return f"زائر {lead.id}"


def _serialize_customer_evidence(row) -> dict:
    return {
        "type": row.evidence_type,
        "source_text": row.source_text,
        "normalized_value": row.normalized_value,
        "confidence": row.confidence,
        "created_at": _iso_utc(row.created_at),
    }


def _serialize_commercial_lineage(row):
    data = {
        "id": row.id,
        "source_message_internal_id": row.source_message_internal_id,
        "objective": row.objective,
        "strategy": row.strategy,
        "next_move": row.next_move,
        "evidence_json": _safe_json_loads(row.evidence_json, []),
        "escalation_required": row.escalation_required,
        "created_at": _iso_utc(row.created_at),
    }
    decision = _safe_json_loads(row.decision_json, {})
    data.update(decision)
    return data

def _build_customer_brief(lead, memory, intelligence, recent_messages, evidence_rows, suggested_replies, product_context=None, company_auto_reply_enabled=None):
    active_suggestion = suggested_replies[0] if suggested_replies else None
    interpretation = interpret_customer_conversation(
        messages=recent_messages,
        evidence_rows=evidence_rows,
        suggestion=active_suggestion,
        lead=lead,
        memory=memory,
        product_context=product_context,
        company_auto_reply_enabled=company_auto_reply_enabled,
    )
    brief = render_customer_brief(interpretation)
    brief["evidence"] = [_serialize_customer_evidence(row) for row in evidence_rows[:5]]
    return brief


def _compact_list(values, limit=5):
    result = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


_OWNER_STATE_LABELS = {
    "EVALUATING": "يقارن الخيارات قبل القرار",
    "QUALIFYING": "يجمع تفاصيل قبل الاختيار",
    "PITCHING": "يناقش خيارات مناسبة",
    "OBJECTION_HANDLING": "لديه اعتراض يحتاج معالجة",
    "CLOSING": "يتقدم نحو إتمام الطلب",
    "GREETING": "في بداية المحادثة",
}


def _owner_display_value(value, fallback="لا توجد بيانات كافية بعد."):
    text = str(value or "").strip()
    if not text:
        return fallback
    return _OWNER_STATE_LABELS.get(text.upper(), text)


def _build_owner_intelligence(
    lead,
    memory,
    intelligence,
    customer_brief,
    sales_state,
    evidence_rows,
    product_context,
    company_auto_reply_enabled=None,
):
    evidence = [_serialize_customer_evidence(row) for row in evidence_rows[:6]]
    evidence_types = {row.evidence_type for row in evidence_rows}
    product_names = _compact_list(
        [
            row.normalized_value or row.source_text
            for row in evidence_rows
            if row.evidence_type == "product_mention"
        ]
        + ([memory.product_interest] if memory and memory.product_interest else [])
    )

    catalog_by_name = {
        getattr(product, "name", "").casefold(): product
        for product in product_context or []
        if getattr(product, "name", None)
    }
    matched_catalog = [
        {
            "name": getattr(product, "name", None),
            "price": getattr(product, "price", None),
            "currency": getattr(product, "currency", None),
        }
        for name in product_names
        for product in [catalog_by_name.get(name.casefold())]
        if product is not None
    ]

    preferences_raw = memory.preferences if memory else ""
    preferences = _safe_json_loads(preferences_raw, {})
    if not isinstance(preferences, dict):
        preferences = {"notes": preferences_raw} if preferences_raw else {}
    communication_profile = preferences.get("communication_profile") or preferences.get("communication") or {}
    if not isinstance(communication_profile, dict):
        communication_profile = {"notes": str(communication_profile)}

    missing_data = customer_brief.get("missing_data") or []
    blockers = []
    if missing_data:
        blockers.append("البيانات التي ما زالت تحتاج تأكيدًا: " + ", ".join(_compact_list(missing_data, limit=6)))
    if "objection_price" in evidence_types:
        blockers.append("العميل أبدى اعتراضًا صريحًا على السعر.")
    if lead.is_paused:
        blockers.append("التولي البشري نشط، لذلك الرد الآلي متوقف مؤقتًا.")
    if company_auto_reply_enabled is False:
        blockers.append("الرد الآلي معطل على مستوى الشركة.")
    if not blockers:
        blockers.append("لا يوجد عائق مثبت حتى الآن.")

    primary_state = sales_state.get("primary_state") or lead.conversation_state or lead.stage
    buyer_intents = sales_state.get("buyer_intents") or []
    if not isinstance(buyer_intents, list):
        buyer_intents = [buyer_intents]

    return {
        "current_situation": {
            "status": _owner_display_value(primary_state),
            "summary": customer_brief.get("business_meaning") or customer_brief.get("what_customer_wants"),
            "latest_signal": customer_brief.get("latest_signal"),
            "evidence": evidence[:3],
        },
        "what_is_blocking": {
            "summary": blockers[0],
            "blockers": blockers,
            "missing_information": _compact_list(missing_data, limit=8),
            "evidence": [item for item in evidence if item["type"] in {"objection_price", "hesitation"}][:3],
        },
        "customer_understanding": {
            "need": customer_brief.get("what_customer_wants") or customer_brief.get("business_meaning"),
            "product_interest": product_names,
            "budget": memory.budget if memory else "",
            "preferences": preferences,
            "buyer_intents": _compact_list(buyer_intents, limit=6),
        },
        "commercial_fit": {
            "stage": lead.stage,
            "conversation_state": lead.conversation_state,
            "known_catalog_matches": matched_catalog,
            "catalog_match_count": len(matched_catalog),
            "opportunity_value": None,
            "note": "Conversation evidence does not establish an authoritative opportunity value.",
        },
        "best_next_action": {
            "action": customer_brief.get("best_next_step") or (intelligence.next_best_action if intelligence else ""),
            "why": customer_brief.get("latest_signal") or (intelligence.action_reason if intelligence else ""),
            "expected_outcome": customer_brief.get("expected_next") or (intelligence.expected_outcome if intelligence else ""),
            "execution_sequence": _safe_json_loads(intelligence.execution_sequence, []) if intelligence and intelligence.execution_sequence else [],
        },
        "relationship_communication": {
            "channel": "web_chat" if lead.channel_type == "VELOR_WEB_CHAT" else "whatsapp",
            "reply_control": "human_takeover" if lead.is_paused else ("auto_reply_disabled" if company_auto_reply_enabled is False else "velor_active"),
            "communication_profile": communication_profile,
            "last_message_sender": lead.last_message_sender,
        },
    }


@router.get("/customers/{lead_id}")
async def get_customer_profile(lead_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from database import LeadMemory, LeadIntelligenceSnapshot, CommercialDecisionLineage, CustomerNote, ActivityLog, WorkspaceSuggestedReply, Message, LeadEvidence, Company, normalize_whatsapp_number, get_phone_variants
    from utils import repair_mojibake
    from services.commercial_authority_service import get_canonical_commercial_view

    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Fetch canonical commercial view
    canonical_view_data = get_canonical_commercial_view(db, company_id, lead_id)
    canonical = canonical_view_data.get("canonical_commercial", {})

    # Existing related data
    notes = db.query(CustomerNote).filter(CustomerNote.lead_id == lead.id).order_by(CustomerNote.created_at.desc()).all()
    activities = db.query(ActivityLog).filter(ActivityLog.lead_id == lead.id).order_by(ActivityLog.timestamp.desc()).all()
    memory = db.query(LeadMemory).filter(LeadMemory.lead_id == lead.id).first()
    # Retained snapshot rows are advisory history only; customer-facing owner
    # surfaces must not use them to fill canonical state or actions.
    intelligence = None
    
    from services.workspace_suggestion_service import active_workspace_suggestions
    suggested_replies = active_workspace_suggestions(db, company_id, lead, limit=5)
    from services.follow_up_service import list_follow_ups, serialize_follow_up
    follow_ups = list_follow_ups(
        db,
        company_id,
        statuses={"pending", "snoozed"},
        lead_id=lead.id,
        limit=50,
    )

    company = db.query(Company).filter(Company.company_id == company_id).first()

    # Re-fetch messages for timeline and interpretation
    from sqlalchemy import desc
    user_id = lead.external_customer_id if lead.channel_type == "VELOR_WEB_CHAT" else lead.whatsapp_jid
    if not user_id:
        user_id = lead.customer_provided_phone or lead.phone or lead.whatsapp_number
    messages = db.query(Message).filter(Message.company_id == company_id, Message.user_id == user_id).order_by(Message.id.desc()).limit(50).all()
    recent_messages = list(reversed(messages))
    
    commercial_lineage = (
        db.query(CommercialDecisionLineage)
        .filter(
            CommercialDecisionLineage.company_id == company_id,
            CommercialDecisionLineage.lead_id == lead.id,
            
        )
        .order_by(CommercialDecisionLineage.created_at.desc())
        .all()
    )
    
    timeline = []
    for msg in recent_messages:
        timeline.append({
            "type": "message",
            "id": f"msg_{msg.internal_message_id}",
            "internal_message_id": msg.internal_message_id,
            "sender": msg.sender,
            "direction": msg.direction,
            "source": getattr(msg, "source", lead.channel_type.lower().replace("velor_", "").replace("_qr", "")),
            "is_ai": (msg.sender == "assistant"),
            "message": msg.message,
            "timestamp": _iso_utc(msg.created_at),
            "delivery_status": msg.delivery_status,
            "status": msg.delivery_status
        })

    evidence_rows = db.query(LeadEvidence).filter(LeadEvidence.company_id == company_id, LeadEvidence.lead_id == lead.id).order_by(LeadEvidence.created_at.desc()).limit(20).all()
    
    # Actually call the builders
    customer_brief = _build_customer_brief(lead, memory, intelligence, recent_messages, evidence_rows, suggested_replies, None, company.bot_auto_reply_enabled if company else None)
    
    owner_intelligence = _build_owner_intelligence(lead, memory, intelligence, customer_brief, {}, evidence_rows, None, company.bot_auto_reply_enabled if company else None)


    try:
        tags_list = json.loads(lead.tags) if lead.tags else []
    except Exception:
        tags_list = []

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    stage_updated_at = lead.stage_updated_at.replace(tzinfo=timezone.utc) if lead.stage_updated_at else lead.created_at.replace(tzinfo=timezone.utc)
    delta = now - stage_updated_at
    time_in_stage = f"{delta.days} يوم" if delta.days > 0 else f"{int(delta.total_seconds() // 3600)} ساعة"

    snapshot_recommendation = None
    
    return {
        "success": True,
        "customer": {
            "id": lead.id,
            "company_id": lead.company_id,
            "name": repair_mojibake(lead.name),
            "phone": lead.phone,
            "whatsapp_number": lead.whatsapp_number,
            "whatsapp_jid": lead.whatsapp_jid,
            "customer_provided_phone": lead.customer_provided_phone,
            "channel_type": lead.channel_type,
            "external_customer_id": lead.external_customer_id,
            "display_phone": lead.customer_provided_phone or lead.phone or lead.whatsapp_number or lead.whatsapp_jid,
            "contact_identifier": lead.external_customer_id if lead.channel_type == "VELOR_WEB_CHAT" else (lead.customer_provided_phone or lead.phone or lead.whatsapp_number or lead.whatsapp_jid),
            "tags": tags_list,
            "is_paused": lead.is_paused,
            "canonical_commercial": canonical,
            "owner_intelligence": owner_intelligence,
            "customer_brief": customer_brief,
            "commercial_execution": {
                "current": _serialize_commercial_lineage(commercial_lineage[0]) if commercial_lineage else None,
                "lineage": [_serialize_commercial_lineage(l) for l in commercial_lineage],
                "note": "تم الاعتماد على التسلسل الهرمي للمعلومات الموثوقة. لا تثبت الاستنتاجات القديمة أي حالة تجارية حالية." if commercial_lineage else "لا تثبت أي معلومات موثوقة."
            },
            "timeline": timeline,
            "suggested_replies": [_serialize_workspace_suggestion(s) for s in suggested_replies],
            "follow_ups": [serialize_follow_up(task) for task in follow_ups],
            "priority_score": None, # Do not fake zero
            "expected_outcome": None,
            "why_matter": None,
            "legacy_advisory": {
                "snapshot_recommendation": snapshot_recommendation
            },
            "permanent_context": {
                "identity": {
                    "name": repair_mojibake(lead.name),
                    "company": None,
                    "revenue_potential": None,
                    "stage": lead.stage,
                    "status": lead.status,
                    "deal_temperature": None,
                    "time_in_stage": time_in_stage,
                },
                "memory": {
                    "summary": memory.customer_summary if memory else "",
                    "preferences": memory.preferences if memory else "",
                    "budget": memory.budget if memory else "",
                    "product_interest": memory.product_interest if memory else "",
                    "purchase_history": memory.purchase_history if memory else "",
                },
            },
            "notes": [
                {
                    "id": n.id,
                    "content": n.content,
                    "author": n.author,
                    "created_at": _iso_utc(n.created_at),
                }
                for n in notes
            ],
            "activity_logs": [
                {
                    "id": a.id,
                    "action_type": a.action_type,
                    "event_type": a.event_type,
                    "description": a.description,
                    "timestamp": _iso_utc(a.timestamp),
                }
                for a in activities
            ]
        }
    }

@router.get("/customers/{lead_id}/suggested-replies")
async def get_customer_suggested_replies(lead_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Customer not found")

    from services.workspace_suggestion_service import active_workspace_suggestions
    suggestions = active_workspace_suggestions(db, company_id, lead, limit=20)

    return {"success": True, "suggested_replies": [_serialize_workspace_suggestion(suggestion) for suggestion in suggestions]}


@router.post("/customers/{lead_id}/suggested-replies/regenerate")
async def regenerate_customer_suggested_replies(lead_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    from services.workspace_suggestion_service import regenerate_workspace_suggestion_variants

    result = await regenerate_workspace_suggestion_variants(db, company_id, lead_id)
    if not result:
        raise HTTPException(status_code=409, detail="No unanswered latest customer turn is available for a grounded draft.")
    return {"success": True, "suggested_reply": result}


@router.patch("/customers/{lead_id}/suggested-replies/{suggestion_id}")
async def update_customer_suggested_reply_status(
    lead_id: int,
    suggestion_id: int,
    data: SuggestionStatusUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if data.status not in {"suggested", "dismissed"}:
        raise HTTPException(status_code=400, detail="Invalid suggestion status")

    suggestion = (
        db.query(WorkspaceSuggestedReply)
        .join(Lead, WorkspaceSuggestedReply.lead_id == Lead.id)
        .filter(
            WorkspaceSuggestedReply.id == suggestion_id,
            WorkspaceSuggestedReply.lead_id == lead_id,
            WorkspaceSuggestedReply.company_id == company_id,
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
        .first()
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggested reply not found")

    if data.status == "suggested" and suggestion.status != "suggested":
        raise HTTPException(status_code=409, detail="A dismissed or stale suggestion cannot be reactivated")
    if data.status == "dismissed" and suggestion.status == "suggested":
        suggestion.status = "dismissed"
        from services.pilot_telemetry_service import record_pilot_event

        record_pilot_event(
            db,
            event_name="suggestion_dismissed",
            company_id=company_id,
            actor_type="owner",
            entity_id=suggestion.id,
            source="workspace",
            idempotency_key=f"suggestion:{suggestion.id}:dismissed",
            metadata={
                "lead_id": lead_id,
                "suggestion_id": suggestion.id,
                "source_message_internal_id": suggestion.source_message_internal_id,
            },
            commit=False,
        )
    elif data.status == "dismissed" and suggestion.status != "dismissed":
        raise HTTPException(status_code=409, detail="Only an active suggestion can be dismissed")
    db.commit()
    db.refresh(suggestion)

    return {"success": True, "suggested_reply": _serialize_workspace_suggestion(suggestion)}


@router.get("/leads")
async def get_crm_leads(page: int = 1, page_size: int = 100, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from utils import repair_mojibake

    leads = (
        db.query(Lead)
        .filter(Lead.company_id == company_id, Lead.is_deleted == False, Lead.is_test == False)
        .order_by(Lead.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    logger.debug("Found %d leads in DB for CRM Grid (company_id: %s)", len(leads), company_id)
    leads_data = []
    for lead in leads:
        try:
            tags_list = json.loads(lead.tags) if lead.tags else []
        except json.JSONDecodeError:
            tags_list = []

        leads_data.append(
            {
                "id": lead.id,
                "name": _merchant_display_name(lead),
                "display_name": _merchant_display_name(lead),
                "phone": lead.phone,
                "whatsapp_number": lead.whatsapp_number,
                "opportunity_value": None, # Hide unproven opportunity value
                "customer_health": None,
                "tags": tags_list,
                "stage": lead.stage,
                "status": lead.status,
                "lead_score": None,
                "ai_summary": _merchant_facing_summary(lead),
                "merchant_summary": _merchant_facing_summary(lead),
                "channel": "دردشة الموقع" if lead.channel_type == "VELOR_WEB_CHAT" else "واتساب",
                "is_paused": lead.is_paused,
                "buyer_intents": [],
                "intent_strength": None,
                "updated_at": _iso_utc(lead.updated_at),
            }
        )

    return {"success": True, "leads": leads_data}


@router.post("/customers/{lead_id}/action")
async def execute_customer_action(
    lead_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    data = await request.json()
    action_label = data.get("action")
    step_id = data.get("step_id")

    if not action_label:
        raise HTTPException(status_code=400, detail="Action label required")

    # Strict isolation: ensure lead belongs to this company
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    log = ActivityLog(
        lead_id=lead_id,
        action_type="Execution",
        event_type="action.executed",
        description=f"Executed AI Recommendation (Step {step_id}): {action_label}",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    try:
        from services.pilot_telemetry_service import record_pilot_event
        record_pilot_event(
            db,
            event_name="first_owner_action",
            company_id=company_id,
            actor_type="owner",
            entity_id=company_id,
            source="workspace",
        )
    except Exception as exc:
        db.rollback()
        logger.warning("Owner action telemetry failed category=%s", exc.__class__.__name__)

    return {"success": True}


