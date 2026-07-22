import json

from jose import jwt

from database import Company, SystemEvent, hash_api_key
from services.pilot_telemetry_service import aggregate_pilot_metrics, record_ai_trace, record_pilot_event


def _token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _company(db, company_id):
    db.add(Company(
        company_id=company_id,
        company_name=company_id,
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-key"),
        plan="PRO",
    ))
    db.commit()


def test_pilot_events_are_idempotent_sanitized_and_aggregated(db):
    _company(db, "metrics_a")
    event = record_pilot_event(
        db,
        event_name="first_public_conversation",
        company_id="metrics_a",
        actor_type="customer",
        entity_id="lead-1",
        source="public_chat",
        metadata={"channel": "VELOR_WEB_CHAT", "message": "private text", "phone": "01000000000"},
    )
    duplicate = record_pilot_event(
        db,
        event_name="first_public_conversation",
        company_id="metrics_a",
        actor_type="customer",
        entity_id="lead-1",
        source="public_chat",
    )
    assert duplicate.id == event.id
    payload = json.loads(event.payload)
    assert payload["metadata"] == {"channel": "VELOR_WEB_CHAT"}
    assert "private text" not in event.payload
    assert "01000000000" not in event.payload

    trace = record_ai_trace(db, company_id="metrics_a", lead_id=1, trace={
        "source_message_id": 7,
        "response_engine_version": "v2",
        "response_path": "FALLBACK",
        "fallback_reason": "provider_unavailable",
        "latency_ms": 12.5,
        "input_tokens_estimate": 100,
        "output_tokens_estimate": 20,
        "model_call_count": 0,
        "semantic_fulfillment": {
            "schema": "velor_semantic_fulfillment_trace_v1",
            "capability": "PRODUCT_DETAILS",
            "requested_slots": ["color"],
            "facts": ["catalog:chair:colors"],
            "unknown_slots": [],
            "verifier_outcome": "EXPLICIT_UNKNOWN",
            "verifier_passed": True,
            "customer_message": "private text",
        },
        "prompt": "secret prompt",
        "customer_message": "private text",
    })
    assert "secret prompt" not in trace.payload
    assert "private text" not in trace.payload
    assert json.loads(trace.payload)["trace"]["semantic_fulfillment"] == {
        "schema": "velor_semantic_fulfillment_trace_v1",
        "capability": "PRODUCT_DETAILS",
        "requested_slots": ["color"],
        "facts": ["catalog:chair:colors"],
        "unknown_slots": [],
        "verifier_outcome": "EXPLICIT_UNKNOWN",
        "verifier_passed": True,
    }

    metrics = aggregate_pilot_metrics(db, "metrics_a")
    assert metrics["activation"]["first_public_conversation"] == 1
    assert metrics["reliability"]["fallback_count"] == 1
    assert metrics["economics"]["input_tokens_estimate"] == 100
    assert metrics["economics"]["estimated"] is True


def test_pilot_metrics_endpoint_is_authenticated_and_tenant_scoped(client, db):
    _company(db, "metrics_tenant_a")
    _company(db, "metrics_tenant_b")
    record_pilot_event(db, event_name="conversation_resolved", company_id="metrics_tenant_a", actor_type="owner", entity_id="a1", source="workspace")
    record_pilot_event(db, event_name="conversation_resolved", company_id="metrics_tenant_b", actor_type="owner", entity_id="b1", source="workspace")

    assert client.get("/api/v1/operations/pilot-metrics").status_code in {401, 403}
    response = client.get(
        "/api/v1/operations/pilot-metrics",
        cookies={"access_token": _token("metrics_tenant_a")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["company_id"] == "metrics_tenant_a"
    assert data["usage"]["conversation_resolved"] == 1
    assert db.query(SystemEvent).filter(SystemEvent.company_id == "metrics_tenant_b").count() == 1
