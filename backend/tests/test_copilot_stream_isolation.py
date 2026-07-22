import asyncio

import pytest

from copilot.stream_service import copilot_event_stream
from engine.intelligence_bus import IntelligenceEvent, bus


@pytest.mark.asyncio
async def test_copilot_stream_drops_unscoped_and_cross_tenant_events():
    generator = copilot_event_stream("stream_company_a")
    next_item = asyncio.create_task(anext(generator))
    await asyncio.sleep(0)

    await bus.publish(IntelligenceEvent(topic="unscoped", payload={}, company_id=None))
    await bus.publish(IntelligenceEvent(topic="other", payload={}, company_id="stream_company_b"))
    expected = IntelligenceEvent(topic="allowed", payload={"safe": True}, company_id="stream_company_a")
    await bus.publish(expected)

    item = await asyncio.wait_for(next_item, timeout=1)
    assert item["id"] == expected.event_id
    assert '"company_id": "stream_company_a"' in item["data"]
    assert "unscoped" not in item["data"]
    assert "other" not in item["data"]
    await generator.aclose()
