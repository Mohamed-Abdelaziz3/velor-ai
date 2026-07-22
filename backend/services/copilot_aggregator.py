from typing import Dict, Any, List
import anyio
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from fastapi import HTTPException

from database import Lead


async def generate_business_snapshot(db: Session, company_id: str) -> Dict[str, Any]:
    """
    Generate a compact, read-only business snapshot for the AI Copilot.
    All queries are restricted by `company_id` and `is_deleted == False` and
    use aggregated SQL (no ORM object hydration).
    """

    def _sync_queries():
        from database import get_live_leads_filter
        live_filter = get_live_leads_filter(Lead)

        # Total leads (not deleted)
        total_leads = db.query(func.count(Lead.id)).filter(Lead.company_id == company_id, Lead.is_deleted.isnot(True), live_filter).scalar() or 0

        # Closed - Won
        closed_won = db.query(func.count(Lead.id)).filter(Lead.company_id == company_id, Lead.is_deleted.isnot(True), Lead.stage == "Won", live_filter).scalar() or 0

        # Closed - Lost
        closed_lost = (
            db.query(func.count(Lead.id)).filter(Lead.company_id == company_id, Lead.is_deleted.isnot(True), Lead.stage == "Lost", live_filter).scalar() or 0
        )

        # Open leads = not Won and not Lost (explicit filter)
        open_leads = (
            db.query(func.count(Lead.id))
            .filter(
                Lead.company_id == company_id, Lead.is_deleted.isnot(True), ~Lead.stage.in_(["Won", "Lost"]), live_filter
            )
            .scalar()
            or 0
        )

        # Revenue aggregation is unsupported / unproven in currency and scope; return None to hide
        revenue_sum = None


        # Top 3 interests/products by count
        interests_q = (
            db.query(Lead.interest.label("interest"), func.count(Lead.id).label("count"))
            .filter(Lead.company_id == company_id, Lead.is_deleted.isnot(True), Lead.interest.isnot(None), Lead.interest != "", live_filter)
            .group_by(Lead.interest)
            .order_by(desc("count"))
            .limit(3)
            .all()
        )
        top_interests: List[Dict[str, Any]] = [{"interest": row.interest, "count": int(row.count)} for row in interests_q]

        # Only explicit operational intervention is authoritative at this
        # aggregate level. Legacy LLM risk projections cannot create urgency.
        at_risk_count = (
            db.query(func.count(Lead.id))
            .filter(
                Lead.company_id == company_id,
                Lead.is_deleted.isnot(True),
                Lead.needs_human_intervention == True,
                live_filter,
            )
            .scalar()
            or 0
        )

        return {
            "total_leads": int(total_leads),
            "open_leads": int(open_leads),
            "closed_won": int(closed_won),
            "closed_lost": int(closed_lost),
            "revenue": None,
            "top_interests": top_interests,
            "at_risk_leads": int(at_risk_count),
        }

    try:
        return await anyio.to_thread.run_sync(_sync_queries)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate snapshot: {exc}")
