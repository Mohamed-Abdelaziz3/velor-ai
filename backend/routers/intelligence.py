"""Evidence-bound intelligence routes for the merchant console."""

from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import Lead, get_db
from routers.auth import get_current_user


router = APIRouter(prefix="/api/v1/intelligence", tags=["Intelligence"])


def _empty_insights(message: str) -> dict:
    return {
        "top_objections": [],
        "trending_products": [],
        "sentiment_trend": None,
        "sentiment_status": "unavailable",
        "strategic_recommendation": message,
        "evidence_scope": "at-risk and lost leads with persisted merchant-visible summaries",
    }


def _local_insights_from_leads(leads: list[Lead]) -> dict:
    """Build bounded observations without sending merchant PII to an LLM."""
    objections: Counter[str] = Counter()
    products: Counter[str] = Counter()
    negative_terms = ("غالي", "مش مناسب", "مشكلة", "إلغاء", "expensive", "cancel", "lost")

    for lead in leads:
        text = f"{lead.ai_summary or ''} {lead.summary or ''} {lead.tags or ''}".casefold()
        if any(term in text for term in negative_terms):
            objections["اعتراض سعر أو ملاءمة مذكور في الملخص"] += 1
        if lead.interest:
            products[str(lead.interest)[:80]] += 1

    return {
        "top_objections": [
            {"objection": label, "frequency": count, "basis": "persisted_summary_match"}
            for label, count in objections.most_common(5)
        ],
        "trending_products": [
            {"product": product, "mention_count": count, "demand": None}
            for product, count in products.most_common(5)
        ],
        "sentiment_trend": None,
        "sentiment_status": "unavailable",
        "strategic_recommendation": (
            "هذه ملاحظات وصفية من السجلات المحفوظة، وليست قياسًا للمبيعات أو للسببية. "
            "راجع المحادثات والأدلة قبل اتخاذ قرار تجاري."
        ),
        "evidence_scope": "at-risk and lost leads with persisted merchant-visible summaries",
    }


@router.get("/insights")
def get_intelligence_insights(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    leads = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
            Lead.status.in_(["at-risk", "lost"]),
        )
        .order_by(Lead.updated_at.desc())
        .limit(50)
        .all()
    )
    if not leads:
        insights = _empty_insights(
            "لا توجد أدلة كافية بعد. اجمع محادثات حقيقية ثم راجع هذه الصفحة."
        )
    else:
        insights = _local_insights_from_leads(leads)
    return {"success": True, "insights": insights}


@router.get("/business-insights")
def get_business_insights(
    days: int = Query(90, ge=1, le=365),
    channel: Literal["all", "whatsapp", "web"] = Query("all"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from services.commercial_intelligence_service import build_business_commercial_intelligence

    return {
        "success": True,
        "data": build_business_commercial_intelligence(db, company_id, days=days, channel=channel),
    }
