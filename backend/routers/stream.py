import asyncio
import json
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse

from database import SessionLocal, SystemEvent

# Using the same auth dependency for consistency
from routers.auth import get_current_user as _get_current_user

logger = logging.getLogger("adam.stream")
router = APIRouter()


def _initial_event_id(company_id: str, header_value: str | None) -> int:
    if header_value not in {None, ""}:
        try:
            value = int(header_value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID header")
        if value < 0:
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID header")
        return value
    db = SessionLocal()
    try:
        max_event = db.query(SystemEvent).filter(
            SystemEvent.company_id == company_id,
        ).order_by(SystemEvent.id.desc()).first()
        return max_event.id if max_event else 0
    finally:
        db.close()


def _format_sse_event(event: SystemEvent) -> str:
    try:
        payload = json.loads(event.payload or "{}")
    except json.JSONDecodeError:
        payload = {"text": str(event.payload or "")[:500]}
    return f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def event_generator(company_id: str, request: Request, last_event_id: int):
    """
    Generator that polls the SystemEvent table for new events scoped to the company_id.
    Yields them in Server-Sent Events (SSE) format.
    """
    # Each poll owns and closes its DB session. A long-lived SSE connection must
    # not retain a transaction or stale ORM identity map.
    while True:
        # If client disconnects, stop yielding
        if await request.is_disconnected():
            break

        # Poll for new events since our last seen ID
        db = SessionLocal()
        try:
            new_events = (
                db.query(SystemEvent)
                .filter(
                    SystemEvent.company_id == company_id,
                    SystemEvent.company_id.isnot(None),
                    SystemEvent.id > last_event_id,
                )
                .order_by(SystemEvent.id.asc())
                .limit(200)
                .all()
            )
            rendered = [(event.id, _format_sse_event(event)) for event in new_events]
        finally:
            db.close()

        for event_id, payload in rendered:
            yield payload
            last_event_id = event_id

        if not rendered:
            yield ": keepalive\n\n"

        # Sleep to prevent burning CPU.
        # A 1-second interval provides near real-time UX without taxing the database.
        await asyncio.sleep(1.0)


@router.get("/api/v1/events/stream")
async def stream_events(request: Request, current_user: dict = Depends(_get_current_user)):
    """
    Establishes an SSE connection for real-time frontend updates.
    """
    company_id = current_user["company_id"]
    last_event_id = _initial_event_id(company_id, request.headers.get("last-event-id"))
    return StreamingResponse(
        event_generator(company_id, request, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
