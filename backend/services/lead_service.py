import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from database import Lead, LeadIntelligenceSnapshot, Notification

log = logging.getLogger("adam.services.lead")


def transition_lead_status(db: Session, lead: Lead, new_status: str) -> None:
    """
    Centralized Domain Service for transitioning a lead's status.
    Ensures cascading updates across Stage, FollowUps, and Intelligence.
    """
    old_status = lead.status
    lead.status = new_status
    lead.updated_at = func.now()

    # Cure the AI Blind Spot: Inject context directly into ai_summary
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    context_update = f"[SYSTEM: Human manually changed lead stage from '{old_status}' to '{new_status}' at {now_str}]"
    lead.ai_summary = f"{lead.ai_summary}\n{context_update}" if lead.ai_summary else context_update

    # Normalize the status for terminal checks
    normalized_status = new_status.lower()
    is_won = normalized_status in ("closed won", "won", "تم البيع ✅", "sale")
    is_lost = normalized_status in ("closed lost", "lost", "مفقود")

    if is_won or is_lost:
        lead.stage = "Won" if is_won else "Lost"
        lead.status = lead.stage
        lead.is_hot_deal = False
        lead.needs_human_intervention = False

        from services.follow_up_service import cancel_for_terminal_lead

        cancel_for_terminal_lead(db, company_id=lead.company_id, lead_id=lead.id, commit=False)
        _freeze_intelligence(db, lead.id)
        _resolve_notifications(db, lead.id)

        log.info(f"Lead {lead.id} transitioned to {lead.stage}. Cascading updates applied.")

    else:
        # For non-terminal status updates, we could optionally map them to stages
        pass


def _freeze_intelligence(db: Session, lead_id: int):
    """Zeroes out priority and risk scores since the deal is closed."""
    snapshot = db.query(LeadIntelligenceSnapshot).filter(LeadIntelligenceSnapshot.lead_id == lead_id).first()
    if snapshot:
        snapshot.priority_score = 0
        snapshot.lost_risk_score = 0


def _resolve_notifications(db: Session, lead_id: int):
    """Marks all active notifications for a lead as read since the deal is closed."""
    db.query(Notification).filter(Notification.lead_id == lead_id, Notification.read_at == None).update(
        {"read_at": func.now()}, synchronize_session=False
    )


def add_manual_note(db: Session, lead: Lead, note_content: str, author: str = "Human User") -> None:
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    context_update = f"[SYSTEM: {author} added manual note at {now_str}: '{note_content}']"
    lead.ai_summary = f"{lead.ai_summary}\n{context_update}" if lead.ai_summary else context_update
    lead.updated_at = func.now()
