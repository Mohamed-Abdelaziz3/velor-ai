import json

import pytest
from fastapi import HTTPException

import routers.stream as stream
from database import Company, SystemEvent, hash_api_key


def test_last_event_id_is_validated_and_missing_starts_at_company_high_water(db, monkeypatch):
    monkeypatch.setattr(stream, "SessionLocal", lambda: db)
    db.add_all([
        Company(
            company_id="sse_a",
            company_name="SSE Company A",
            email="sse-a@example.com",
            password="hashed",
            api_key_hash=hash_api_key("sse-a-api-key"),
        ),
        Company(
            company_id="sse_b",
            company_name="SSE Company B",
            email="sse-b@example.com",
            password="hashed",
            api_key_hash=hash_api_key("sse-b-api-key"),
        ),
    ])
    db.flush()
    db.add_all([
        SystemEvent(company_id="sse_a", event_type="one", entity_id="1", payload="{}"),
        SystemEvent(company_id="sse_b", event_type="other", entity_id="2", payload="{}"),
        SystemEvent(company_id="sse_a", event_type="two", entity_id="3", payload="{}"),
    ])
    db.commit()
    expected = db.query(SystemEvent).filter(SystemEvent.company_id == "sse_a").order_by(SystemEvent.id.desc()).first().id

    assert stream._initial_event_id("sse_a", None) == expected
    assert stream._initial_event_id("sse_a", "0") == 0
    assert stream._initial_event_id("sse_a", str(expected - 1)) == expected - 1
    with pytest.raises(HTTPException):
        stream._initial_event_id("sse_a", "not-a-number")
    with pytest.raises(HTTPException):
        stream._initial_event_id("sse_a", "-1")


def test_sse_format_contains_monotonic_id_and_json_safe_payload():
    event = SystemEvent(id=42, company_id="sse_company", event_type="canonical_commercial.updated", entity_id="7", payload=json.dumps({"lead_id": 7}))
    rendered = stream._format_sse_event(event)
    assert rendered.startswith("id: 42\nevent: canonical_commercial.updated\n")
    assert 'data: {"lead_id": 7}' in rendered

    malformed = SystemEvent(id=43, company_id="sse_company", event_type="bad", entity_id="8", payload='bad " payload\n')
    rendered_bad = stream._format_sse_event(malformed)
    data_line = next(line for line in rendered_bad.splitlines() if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: "))["text"].startswith("bad")
