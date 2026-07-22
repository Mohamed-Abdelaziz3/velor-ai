import asyncio
from typing import AsyncGenerator
from sse_starlette.sse import EventSourceResponse
from engine.intelligence_bus import bus
import logging

logger = logging.getLogger(__name__)

async def copilot_event_stream(company_id: str) -> AsyncGenerator[dict, None]:
    """
    Async generator that subscribes to the IntelligenceBus and yields events for SSE.
    """
    queue = await bus.subscribe()
    logger.info(f"[SSE] Client connected for company: {company_id}")
    
    try:
        while True:
            # Wait for an event from the bus
            event = await queue.get()
            
            # Tenant-facing streams fail closed. Unscoped process events are
            # operational signals and must never be broadcast to every tenant.
            if not event.company_id or event.company_id != company_id:
                continue
                
            yield {
                "id": event.event_id,
                "event": "message",
                "data": event.to_json()
            }
    except asyncio.CancelledError:
        logger.info(f"[SSE] Client disconnected for company: {company_id}")
    finally:
        await bus.unsubscribe(queue)

def get_stream_response(company_id: str) -> EventSourceResponse:
    """
    Returns an EventSourceResponse that streams live Intelligence events.
    """
    return EventSourceResponse(copilot_event_stream(company_id))
