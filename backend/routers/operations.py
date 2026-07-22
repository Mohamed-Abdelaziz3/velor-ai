from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from services.follow_up_service import list_follow_ups, serialize_follow_up, transition_follow_up
from services.pilot_telemetry_service import aggregate_pilot_metrics, record_client_product_events
from services.recovery_impact_service import build_recovery_impact


router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


class SnoozeRequest(BaseModel):
    snoozed_until: datetime


class ClientTelemetryEvent(BaseModel):
    event_name: str = Field(min_length=1, max_length=80)
    client_event_id: str = Field(min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientTelemetryBatch(BaseModel):
    events: list[ClientTelemetryEvent] = Field(min_length=1, max_length=50)


@router.get("/pilot-metrics")
def pilot_metrics(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"success": True, "data": aggregate_pilot_metrics(db, current_user["company_id"])}


@router.get("/follow-ups")
def get_follow_ups(
    status: Optional[str] = Query(None),
    lead_id: Optional[int] = Query(None, ge=1),
    due_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statuses = [item.strip().lower() for item in status.split(",") if item.strip()] if status else None
    try:
        tasks = list_follow_ups(
            db,
            current_user["company_id"],
            statuses=statuses,
            lead_id=lead_id,
            due_only=due_only,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "follow_ups": [serialize_follow_up(task) for task in tasks]}


def _transition_response(
    db: Session,
    company_id: str,
    task_id: int,
    status: str,
    *,
    snoozed_until: Optional[datetime] = None,
) -> dict[str, Any]:
    try:
        task = transition_follow_up(
            db,
            company_id=company_id,
            task_id=task_id,
            target_status=status,
            snoozed_until=snoozed_until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409 if str(exc) == "invalid_follow_up_transition" else 400, detail=str(exc)) from exc
    if not task:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return {"success": True, "follow_up": serialize_follow_up(task)}


@router.post("/follow-ups/{task_id}/complete")
def complete_follow_up(task_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition_response(db, current_user["company_id"], task_id, "completed")


@router.post("/follow-ups/{task_id}/dismiss")
def dismiss_follow_up(task_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition_response(db, current_user["company_id"], task_id, "dismissed")


@router.post("/follow-ups/{task_id}/snooze")
def snooze_follow_up(
    task_id: int,
    payload: SnoozeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _transition_response(
        db,
        current_user["company_id"],
        task_id,
        "snoozed",
        snoozed_until=payload.snoozed_until,
    )


@router.post("/telemetry")
def product_telemetry(
    payload: ClientTelemetryBatch,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rows = record_client_product_events(
            db,
            company_id=current_user["company_id"],
            events=[event.model_dump() for event in payload.events],
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "accepted": len(rows)}


@router.get("/recovery-impact")
def recovery_impact(
    days: int = Query(30, ge=1, le=365),
    channel: Literal["all", "whatsapp", "web"] = Query("all"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "success": True,
        "data": build_recovery_impact(
            db,
            current_user["company_id"],
            days=days,
            channel=channel,
        ),
    }
