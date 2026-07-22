import asyncio
import json
import logging
import uuid
from typing import Dict, Any, List, Callable, Awaitable
from datetime import datetime, timezone
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class EventSeverity:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

class IntelligenceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    topic: str
    severity: str = EventSeverity.INFO
    payload: Dict[str, Any]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    company_id: str | None = None  # Required by tenant-facing stream consumers.
    
    def to_json(self) -> str:
        return json.dumps(self.model_dump(), default=str)

class IntelligenceBus:
    """
    Singleton Event Bus (PubSub) for the Velor AI Command Center.
    Handles streaming of events across the application decoupled from DB polling.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(IntelligenceBus, cls).__new__(cls)
            cls._instance._subscribers = []
            cls._instance._lock = asyncio.Lock()
        return cls._instance
    
    async def subscribe(self) -> asyncio.Queue:
        """
        Subscribe to all events on the bus.
        Returns an asyncio.Queue that receives IntelligenceEvent instances.
        """
        queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(queue)
        return queue
        
    async def unsubscribe(self, queue: asyncio.Queue):
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)
                
    async def publish(self, event: IntelligenceEvent):
        """
        Publish an event to all active subscribers.
        """
        async with self._lock:
            for queue in self._subscribers:
                await queue.put(event)
        
        # Log critical/high events for backend tracing
        if event.severity in [EventSeverity.CRITICAL, EventSeverity.HIGH]:
            logger.info(f"[IntelligenceBus] {event.severity} | {event.topic} | CID: {event.company_id}")

    def publish_sync(self, event: IntelligenceEvent):
        """
        Synchronous wrapper to fire-and-forget publish from sync contexts (e.g. SQLAlchemy/DB helpers)
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            pass # No running loop

# Instantiate the singleton bus
bus = IntelligenceBus()
