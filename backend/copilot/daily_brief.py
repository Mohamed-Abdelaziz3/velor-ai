"""Deterministic Copilot projections.

These compatibility-shaped responses deliberately exclude
``LeadIntelligenceSnapshot``.  Active priority, risk, and action data comes from
source-backed priority actions and owner-attention projections.
"""

from collections import Counter
import os
from typing import Any, Dict, List

import httpx

from sqlalchemy.orm import Session

from database import CommercialEvent, Lead, get_open_leads_query
from services.owner_attention_projection_service import get_owner_attention_projection
from services.priority_actions_service import get_priority_actions


def get_whatsapp_status(company_id: str) -> str:
    """Bounded channel status probe retained for compatibility-only empty states."""
    node_url = os.getenv("NODE_GATEWAY_URL", "http://127.0.0.1:3005")
    secret = os.getenv("NODE_INTERNAL_SECRET", "")
    try:
        with httpx.Client(timeout=0.5) as client:
            response = client.get(f"{node_url}/api/whatsapp/status/{company_id}", headers={"X-Internal-Secret": secret})
            if response.status_code == 200 and response.json().get("success"):
                status = response.json().get("status")
                if status in {"connected", "already_running"}:
                    return "CONNECTED"
                if status in {"disconnected", "logged_out", "stale", "not_found"}:
                    return "DISCONNECTED"
    except Exception:
        pass
    return "UNKNOWN"


def _actions(db: Session, company_id: str) -> List[Dict[str, Any]]:
    return get_priority_actions(db, company_id, limit=5).get("actions", [])


def _attention(db: Session, company_id: str) -> List[Dict[str, Any]]:
    return get_owner_attention_projection(db, company_id, limit=10).get("items", [])


def generate_daily_brief(db: Session, company_id: str) -> Dict[str, Any]:
    actions = _actions(db, company_id)
    attention = _attention(db, company_id)
    open_count = get_open_leads_query(db, company_id).count()
    ready = sum(1 for item in attention if item.get("projection_class") == "READY_TO_CLOSE")
    waiting = sum(1 for item in attention if item.get("projection_class") == "WAITING_ON_US")
    risk = sum(1 for item in attention if item.get("projection_class") in {"STUCK_ON_OBJECTION", "REGRESSING"})
    if not open_count:
        channel = get_whatsapp_status(company_id)
        if channel == "DISCONNECTED":
            headline = "اربط قناة لبدء استقبال المحادثات"
            context = "يرجى ربط قناة واتساب لإتاحة المزامنة واستقبال الرسائل."
        elif channel == "CONNECTED":
            headline = "تم ربط القناة بنجاح"
            context = "المنصة متصلة بـ WhatsApp وبانتظار استقبال أولى محادثات عملائك."
        else:
            headline = "تعذر التحقق من حالة القناة حالياً"
            context = "يرجى التحقق من اتصال الخادم أو المحاولة مرة أخرى."
    elif actions:
        headline = "توجد إجراءات مصدرها أدلة موثقة تحتاج إلى مراجعة."
        context = "تُعرض فقط الحالات ذات الدليل أو الحالة التشغيلية الموثقة."
    else:
        has_context = any((lead.ai_summary or "").strip() for lead in get_open_leads_query(db, company_id).all())
        if has_context:
            headline = f"تمت مراجعة {open_count} محادثات."
            context = "لا توجد إجراءات عاجلة مقترحة حالياً."
        else:
            headline = "لا توجد بيانات كافية"
            context = "البيانات المتاحة غير كافية لتقديم تحليلات أو توصيات حالياً."
    return {
        "ready_to_purchase": ready,
        "needs_followup": waiting,
        "at_risk": risk,
        "new_conversations_today": None,
        "revenue_at_risk": None,
        "velor_narrative": {"headline": headline, "context": context},
        "best_action": actions[0].get("suggested_action") if actions else None,
        "confidence_score": None,
    }


def get_top_opportunities(db: Session, company_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "lead_id": item["lead_id"],
            "name": item.get("lead_name"),
            "phone": None,
            "stage": None,
            "priority_score": item.get("score"),
            "why_it_matters": item.get("description"),
            "recommended_action": item.get("suggested_action"),
            "opportunity_value": None,
        }
        for item in _actions(db, company_id)
    ]


def get_top_risks(db: Session, company_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "lead_id": item["lead_id"],
            "name": item.get("lead_name"),
            "phone": None,
            "lost_risk_score": None,
            "risk_reason": item.get("why"),
            "recommended_action": item.get("what_next"),
            "opportunity_value": None,
            "reason_code": item.get("reason_code"),
        }
        for item in _attention(db, company_id)
        if item.get("projection_class") in {"WAITING_ON_US", "STUCK_ON_OBJECTION", "REGRESSING"}
    ][:3]


def get_recommended_actions(db: Session, company_id: str) -> List[Dict[str, Any]]:
    return _actions(db, company_id)


def get_executive_summary(db: Session, company_id: str) -> Dict[str, Any]:
    actions = _actions(db, company_id)
    attention = _attention(db, company_id)
    active = get_open_leads_query(db, company_id).count()
    return {
        "total_active_leads": active,
        "purchase_ready_count": sum(1 for item in attention if item.get("projection_class") == "READY_TO_CLOSE"),
        "high_intent_count": None,
        "lost_candidates_count": sum(1 for item in attention if item.get("projection_class") in {"STUCK_ON_OBJECTION", "REGRESSING"}),
        "money_left_on_table": None,
        "top_recommendation": actions[0].get("suggested_action") if actions else None,
    }


def get_global_product_stats(db: Session, company_id: str) -> Dict[str, Any]:
    rows = (
        db.query(CommercialEvent.product_ref)
        .filter(
            CommercialEvent.company_id == company_id,
            CommercialEvent.product_ref.isnot(None),
            CommercialEvent.event_type.in_(("PRODUCT_MENTIONED", "PRODUCT_ASKED_ABOUT", "PRODUCT_CONSIDERED", "PRODUCT_SELECTED")),
        )
        .all()
    )
    counts = Counter(row[0] for row in rows if row[0])
    products = [{"product_name": name, "total_requests": count, "sentiment_summary": None} for name, count in counts.most_common(5)]
    return {"hero_product": products[0] if products else None, "top_products": products[1:]}
