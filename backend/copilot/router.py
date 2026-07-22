from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import re

from main import limiter

from database import get_db
from routers.auth import get_current_user

from copilot.daily_brief import (
    generate_daily_brief,
    get_recommended_actions,
    get_top_opportunities,
    get_top_risks,
    get_executive_summary,
    get_global_product_stats,
)
from services.copilot_aggregator import generate_business_snapshot

router = APIRouter(prefix="/api/v1/copilot", tags=["Copilot"])

def get_copilot_company_id(
    request: Request,
    user: dict = Depends(get_current_user),
) -> str:
    cid = user["company_id"]
    query_cid = request.query_params.get("company_id")
    if user["role"] == "super_admin":
        if not query_cid:
            return cid
        if not re.fullmatch(r"[\w-]+", query_cid):
            raise HTTPException(status_code=400, detail="Invalid company_id")
        return query_cid
    if query_cid and query_cid != cid:
        raise HTTPException(status_code=403, detail="Not allowed")
    return cid


@router.get("/brief", response_model=Dict[str, Any])
def get_brief_endpoint(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    return {"success": True, "data": generate_daily_brief(db, target_cid)}


from copilot.stream_service import get_stream_response

@router.get("/stream")
def get_copilot_stream(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    return get_stream_response(target_cid)

@router.get("/timeline", response_model=Dict[str, Any])
def get_historical_timeline(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    from database import Message, Lead
    from sqlalchemy import desc
    from utils import repair_mojibake

    # Get latest 10 messages
    recent_msgs = (
        db.query(Message, Lead.name, Lead.phone)
        .join(Lead, Message.user_id == Lead.whatsapp_number)
        .filter(
            Lead.company_id == target_cid,
            Message.company_id == target_cid,
        )
        .order_by(desc(Message.created_at))
        .limit(10)
        .all()
    )

    events = []
    for msg, lead_name, lead_phone in recent_msgs:
        name = repair_mojibake(lead_name) or lead_phone or "New Customer"
        sender = msg.sender
        topic = "message.received" if sender == "user" else "message.sent"
        text_content = repair_mojibake(msg.message)
        
        events.append({
            "topic": topic,
            "severity": "INFO",
            "timestamp": msg.created_at.isoformat() if msg.created_at else "",
            "payload": {
                "text": f"{name}: {text_content[:50]}..." if text_content else f"{name} interacted.",
                "lead_id": lead_phone
            }
        })
    
    return {"success": True, "data": events}

@router.get("/snapshot", response_model=Dict[str, Any])
async def get_copilot_snapshot(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    return await generate_business_snapshot(db, target_cid)


@router.get("/opportunities", response_model=List[Dict[str, Any]])
def get_opportunities_endpoint(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    return get_top_opportunities(db, target_cid)


@router.get("/risks", response_model=List[Dict[str, Any]])
def get_risks_endpoint(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    return get_top_risks(db, target_cid)


@router.get("/actions", response_model=List[Dict[str, Any]])
def get_actions_endpoint(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    from services.priority_actions_service import get_priority_actions

    priority_actions = get_priority_actions(db, target_cid, limit=5)["actions"]
    if priority_actions:
        return priority_actions
    return get_recommended_actions(db, target_cid)


@router.get("/queue", response_model=Dict[str, Any])
def get_commercial_queue_endpoint(db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    from services.owner_attention_projection_service import get_commercial_queue
    return {"success": True, "data": get_commercial_queue(db, target_cid, limit=25)}


@router.get("/summary", response_model=Dict[str, Any])
@limiter.limit("10/minute")
def get_summary_endpoint(request: Request, db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    return {"success": True, "data": get_executive_summary(db, target_cid)}


@router.get("/global-product-stats", response_model=Dict[str, Any])
@limiter.limit("10/minute")
def get_global_product_stats_endpoint(request: Request, db: Session = Depends(get_db), target_cid: str = Depends(get_copilot_company_id)):
    data = get_global_product_stats(db, target_cid)
    return {"success": True, "data": data}


@router.post("/product-analysis")
@limiter.limit("5/minute")
def trigger_product_analysis(
    request: Request,
    lead_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    target_cid: str = Depends(get_copilot_company_id),
):
    from database import Lead, LeadAnalytics
    import json

    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == target_cid).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Check if we already have recent analytics (within last 24h)
    analytics = db.query(LeadAnalytics).filter(LeadAnalytics.lead_id == lead_id).first()

    # Trigger background task regardless of whether it's recent or not to refresh it
    from engine.analytics_worker import analyze_lead_product_interest

    background_tasks.add_task(analyze_lead_product_interest, target_cid, lead.whatsapp_number, lead.id)

    # Return what we have for now, or indicate processing
    if analytics and analytics.top_requested_products:
        return {
            "success": True,
            "status": "refreshing_in_background",
            "data": {
                "top_requested_products": json.loads(analytics.top_requested_products),
                "trending_topics": json.loads(analytics.trending_topics) if analytics.trending_topics else [],
                "business_opportunity": analytics.business_opportunity,
                "last_analyzed_at": analytics.last_analyzed_at,
            },
        }

    return {"success": True, "status": "processing", "message": "Product analysis has been queued and will be ready shortly."}
