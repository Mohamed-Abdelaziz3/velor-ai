import asyncio

from services import v2_turn_use_case


def test_execute_v2_turn_keeps_decision_and_persistence_seams(monkeypatch):
    observed = {}

    async def fake_get(**kwargs):
        observed["get"] = kwargs
        return {
            "answer_text": "reply",
            "response_envelope": {"schema": "test"},
            "trace": {
                "lead_to_save": {"status": "new"},
                "action_decision": "action",
                "sales_snapshot": "sales",
                "objection_snapshot": "objection",
                "recommendation_decision": "recommendation",
                "conversation_action": {"type": "NONE"},
            },
        }

    def fake_persist(**kwargs):
        observed["persist"] = kwargs
        return {
            "internal_id": "out-1",
            "lead_id": 7,
            "public_message_id": "pub-1",
        }

    monkeypatch.setattr(v2_turn_use_case.velor_chat_v2, "get_v2_ai_response", fake_get)
    monkeypatch.setattr(
        v2_turn_use_case.public_chat_turn_service,
        "persist_v2_public_turn_atomic",
        fake_persist,
    )

    result = asyncio.run(
        v2_turn_use_case.execute_v2_turn(
            db=object(),
            company=object(),
            lead=object(),
            source_message=object(),
            company_id="co",
            lead_id=7,
            user_id="user",
            customer_text="hello",
            inbound_internal_id="in-1",
            processing_claim_attempt=2,
            background_tasks="bg",
            channel_type="WHATSAPP_QR",
            source_route="/chat",
            outbound_delivery_status="pending",
            telemetry_source="whatsapp_gateway",
        )
    )

    assert result["result"]["answer_text"] == "reply"
    assert result["persisted"]["internal_id"] == "out-1"
    assert observed["get"]["channel_type"] == "WHATSAPP_QR"
    assert observed["get"]["source_route"] == "/chat"
    assert observed["persist"]["channel_type"] == "WHATSAPP_QR"
    assert observed["persist"]["outbound_delivery_status"] == "pending"
    assert observed["persist"]["telemetry_source"] == "whatsapp_gateway"
    assert observed["persist"]["enforce_auto_reply_guard"] is True
    assert observed["persist"]["inbound_internal_id"] == "in-1"
