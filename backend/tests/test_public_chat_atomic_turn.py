import uuid
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from database import (
    CommercialDecisionLineage,
    Company,
    CompanyKnowledge,
    LeadMemory,
    Message,
    Lead,
    LeadEvent,
    SystemEvent,
    WorkspaceSuggestedReply,
    hash_api_key,
)


def _company(db):
    suffix = uuid.uuid4().hex[:8]
    company = Company(
        company_id=f"atomic_{suffix}",
        company_name="Atomic Company",
        email=f"atomic_{suffix}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"atomic-{suffix}"),
        plan="PRO",
        is_web_chat_enabled=True,
        public_chat_slug=f"atomic-{suffix}",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company.company_id,
            system_prompt="Use trusted facts only.",
            products_data='[{"name":"Chair","price":100}]',
            welcome_message="Welcome",
            suggested_questions="",
        )
    )
    db.commit()
    return company


def _canonical_events(db, company_id):
    return db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "canonical_commercial.updated",
    )


def test_v2_public_turn_is_atomic_and_duplicate_does_not_call_provider(client, db, monkeypatch):
    import services.velor_chat_v2 as v2

    company = _company(db)
    session = client.post(f"/api/public/companies/{company.public_chat_slug}/session").json()
    token = session["token"]
    client_message_id = f"atomic-{uuid.uuid4().hex}"
    provider_calls = 0

    async def fake_v2(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {
            "answer_text": "Trusted answer",
            "response_envelope": {
                "message": {"text": "Trusted answer", "language": "en"},
                "presentation": {"product_cards": [], "quick_replies": [], "conversation_action": {"type": "START_HUMAN_HANDOFF", "status": "executed"}},
                "meta": {"response_path": "FALLBACK", "handoff_active": True},
            },
            "trace": {
                "lead_to_save": {
                    "preference_memory_snapshot": {
                        "company_id": company.company_id,
                        "lead_id": "1",
                        "active_preferences": [
                            {
                                "memory_id": "pref-black",
                                "company_id": company.company_id,
                                "lead_id": "1",
                                "dimension": "COLOR",
                                "polarity": "PREFER",
                                "value": "black",
                                "scope": "GLOBAL",
                                "explicitness": "EXPLICIT",
                                "stability": "STABLE",
                                "confidence": 1.0,
                                "status": "ACTIVE",
                                "evidence_refs": ["current_message"],
                                "reason_codes": ["EXPLICIT_COLOR_STATEMENT"],
                            }
                        ],
                    },
                    "communication_profile_snapshot": {
                        "company_id": company.company_id,
                        "lead_id": "1",
                        "effective_for_current_turn": {"VERBOSITY": "BRIEF"},
                    },
                },
                "action_decision": None,
                "sales_snapshot": None,
                "objection_snapshot": None,
                "recommendation_decision": None,
                "response_path": "FALLBACK",
                "response_plan_type": "ANSWER",
                "conversation_action": {"type": "START_HUMAN_HANDOFF", "status": "executed"},
            },
        }

    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(v2, "get_v2_ai_response", fake_v2)
    request = {
        "message": "Tell me about the chair",
        "client_message_id": client_message_id,
    }
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post("/api/public/chat", json=request, headers=headers)
    duplicate = client.post("/api/public/chat", json=request, headers=headers)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["response"]["meta"]["handoff_active"] is True
    assert provider_calls == 1
    db.expire_all()
    turns = db.query(Message).filter(Message.company_id == company.company_id).all()
    assert len([row for row in turns if row.direction == "incoming"]) == 1
    assert len([row for row in turns if row.direction == "outgoing" and row.sender == "assistant"]) == 1
    assert db.query(CommercialDecisionLineage).filter(
        CommercialDecisionLineage.company_id == company.company_id
    ).count() == 1
    assert _canonical_events(db, company.company_id).count() == 1
    assert next(row for row in turns if row.direction == "incoming").processing_status == "completed"
    persisted_lead = db.query(Lead).filter(
        Lead.company_id == company.company_id
    ).one()
    persisted_memory = db.query(LeadMemory).filter(
        LeadMemory.lead_id == persisted_lead.id
    ).one()
    persisted_preferences = json.loads(persisted_memory.preferences)
    assert persisted_preferences["active_preferences"][0]["value"] == "black"
    assert (
        persisted_preferences["communication_profile"]["effective_for_current_turn"]["VERBOSITY"]
        == "BRIEF"
    )
    refreshed = client.get(f"/api/public/companies/{company.public_chat_slug}/session", headers=headers)
    assert refreshed.status_code == 200
    persisted_reply = next(row for row in refreshed.json()["conversations"] if row["sender"] == "assistant")
    assert persisted_reply["response"]["presentation"]["conversation_action"]["status"] == "executed"


def test_v2_generation_failure_rolls_back_its_uncommitted_inbound_claim(client, db, monkeypatch):
    """A failed V2 response must not leave a lease or any observable turn state."""
    import services.velor_chat_v2 as v2

    company = _company(db)
    session = client.post(f"/api/public/companies/{company.public_chat_slug}/session").json()

    async def failed_v2(**_kwargs):
        raise RuntimeError("planned_generation_failure")

    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(v2, "get_v2_ai_response", failed_v2)
    response = client.post(
        "/api/public/chat",
        json={"message": "Tell me about the chair", "client_message_id": f"fail-{uuid.uuid4().hex}"},
        headers={"Authorization": f"Bearer {session['token']}"},
    )

    assert response.status_code == 500
    db.expire_all()
    assert db.query(Message).filter(Message.company_id == company.company_id).count() == 0
    assert db.query(SystemEvent).filter(SystemEvent.company_id == company.company_id).count() == 0
    assert db.query(CommercialDecisionLineage).filter(
        CommercialDecisionLineage.company_id == company.company_id
    ).count() == 0


def test_atomic_helper_rolls_back_reply_lineage_and_invalidation_together(db, monkeypatch):
    from database import Lead
    from services import public_chat_turn_service as service

    company = _company(db)
    lead = Lead(
        company_id=company.company_id,
        name="Customer",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id="wc_v_atomic_rollback",
    )
    db.add(lead)
    db.commit()
    incoming = Message(
        internal_message_id=f"incoming-{uuid.uuid4().hex}",
        public_message_id=f"pub-{uuid.uuid4().hex}",
        wa_message_id=f"wc:{company.company_id}:{uuid.uuid4().hex}",
        company_id=company.company_id,
        user_id=lead.external_customer_id,
        sender="user",
        direction="incoming",
        message="Hello",
        delivery_status="received",
        processing_status="processing",
        processing_attempts=1,
    )
    db.add(incoming)
    db.commit()

    def fail_lineage(*_args, **_kwargs):
        raise RuntimeError("lineage_write_failed")

    monkeypatch.setattr(service, "persist_commercial_turn_in_session", fail_lineage)
    with pytest.raises(RuntimeError, match="lineage_write_failed"):
        service.persist_v2_public_turn_atomic(
            company_id=company.company_id,
            lead_id=lead.id,
            user_id=lead.external_customer_id,
            customer_text="Hello",
            assistant_text="Reply",
            inbound_internal_id=incoming.internal_message_id,
            processing_claim_attempt=1,
            lead_update=None,
            decision=None,
            sales_snapshot=None,
        )

    db.expire_all()
    assert db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "outgoing",
    ).count() == 0
    assert db.query(CommercialDecisionLineage).filter(
        CommercialDecisionLineage.company_id == company.company_id
    ).count() == 0
    assert _canonical_events(db, company.company_id).count() == 0
    assert db.query(Message).filter(Message.id == incoming.id).one().processing_status == "processing"


def _processing_inbound(db, company, lead, text="Hello"):
    incoming = Message(
        internal_message_id=f"incoming-{uuid.uuid4().hex}",
        public_message_id=f"pub-{uuid.uuid4().hex}",
        wa_message_id=f"wc:{company.company_id}:{uuid.uuid4().hex}",
        company_id=company.company_id,
        user_id=lead.external_customer_id,
        sender="user",
        direction="incoming",
        message=text,
        delivery_status="received",
        processing_status="processing",
        processing_attempts=1,
    )
    db.add(incoming)
    db.commit()
    return incoming


def test_late_takeover_fences_generated_reply_and_preserves_pause(db):
    from services.public_chat_turn_service import persist_v2_public_turn_atomic

    company = _company(db)
    lead = Lead(
        company_id=company.company_id,
        name="Customer",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=f"wc_v_takeover_{uuid.uuid4().hex}",
        is_paused=False,
    )
    db.add(lead)
    db.commit()
    incoming = _processing_inbound(db, company, lead, text="Can you help?")

    # Simulate an owner takeover committed after generation captured False.
    lead.is_paused = True
    db.commit()
    result = persist_v2_public_turn_atomic(
        db=db,
        company_id=company.company_id,
        lead_id=lead.id,
        user_id=lead.external_customer_id,
        customer_text=incoming.message,
        assistant_text="Stale generated answer",
        inbound_internal_id=incoming.internal_message_id,
        processing_claim_attempt=1,
        lead_update={"is_paused": False},
        decision=None,
        sales_snapshot=None,
        enforce_auto_reply_guard=True,
    )

    db.expire_all()
    assert result["auto_reply_skipped"] is True
    assert result["reason"] == "human_takeover_active"
    assert db.query(Lead).filter(Lead.id == lead.id).one().is_paused is True
    assert db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "outgoing",
        Message.sender == "assistant",
    ).count() == 0
    assert db.query(Message).filter(Message.id == incoming.id).one().processing_status == "intentionally_skipped"
    assert db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company.company_id,
        WorkspaceSuggestedReply.source_message_internal_id == incoming.internal_message_id,
    ).count() == 1


def test_owner_reply_after_generation_fences_auto_reply_without_new_suggestion(db):
    from services.public_chat_turn_service import persist_v2_public_turn_atomic

    company = _company(db)
    lead = Lead(
        company_id=company.company_id,
        name="Customer",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=f"wc_v_owner_reply_{uuid.uuid4().hex}",
    )
    db.add(lead)
    db.commit()
    incoming = _processing_inbound(db, company, lead, text="Is it available?")
    db.add(
        Message(
            company_id=company.company_id,
            user_id=lead.external_customer_id,
            sender="owner",
            direction="outgoing",
            message="I am checking that now.",
            internal_message_id=f"owner-{uuid.uuid4().hex}",
            delivery_status="sent",
        )
    )
    db.commit()

    result = persist_v2_public_turn_atomic(
        db=db,
        company_id=company.company_id,
        lead_id=lead.id,
        user_id=lead.external_customer_id,
        customer_text=incoming.message,
        assistant_text="Stale generated answer",
        inbound_internal_id=incoming.internal_message_id,
        processing_claim_attempt=1,
        lead_update={"is_paused": False},
        decision=None,
        sales_snapshot=None,
        enforce_auto_reply_guard=True,
    )

    assert result["auto_reply_skipped"] is True
    assert result["reason"] == "owner_replied"
    assert db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.sender == "assistant",
    ).count() == 0
    assert db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company.company_id,
    ).count() == 0


@pytest.mark.parametrize(
    "failure_stage",
    (
        "inbound_projection",
        "lead_update",
        "outbound",
        "message_event",
        "response_event",
        "action",
        "commercial",
        "invalidation",
        "telemetry",
        "claim_completion",
    ),
)
def test_every_public_turn_persistence_stage_rolls_back_together(db, failure_stage):
    from services.public_chat_turn_service import persist_v2_public_turn_atomic

    company = _company(db)
    lead = Lead(
        company_id=company.company_id,
        name="Customer",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=f"wc_v_fault_{uuid.uuid4().hex}",
    )
    db.add(lead)
    db.commit()
    incoming = _processing_inbound(db, company, lead)

    with pytest.raises(RuntimeError, match=f"public_turn_fault:{failure_stage}"):
        persist_v2_public_turn_atomic(
            company_id=company.company_id,
            lead_id=lead.id,
            user_id=lead.external_customer_id,
            customer_text=incoming.message,
            assistant_text="Reply",
            inbound_internal_id=incoming.internal_message_id,
            processing_claim_attempt=1,
            lead_update={"pending_question": "state"},
            decision=None,
            sales_snapshot=None,
            conversation_action={"type": "START_HUMAN_HANDOFF", "status": "executed"},
            trace={"source_message_id": incoming.id, "response_path": "FALLBACK", "response_plan_type": "ANSWER"},
            failure_stage=failure_stage,
        )

    db.expire_all()
    assert db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "outgoing").count() == 0
    assert db.query(CommercialDecisionLineage).filter(CommercialDecisionLineage.company_id == company.company_id).count() == 0
    assert _canonical_events(db, company.company_id).count() == 0
    assert db.query(LeadEvent).filter(LeadEvent.lead_id == lead.id).count() == 0
    assert db.query(Message).filter(Message.id == incoming.id).one().processing_status == "processing"


def test_concurrent_acceptance_cannot_execute_the_same_action_twice(db):
    from services.public_chat_turn_service import persist_v2_public_turn_atomic

    company = _company(db)
    lead = Lead(
        company_id=company.company_id,
        name="Customer",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=f"wc_v_race_{uuid.uuid4().hex}",
    )
    db.add(lead)
    db.commit()
    incoming = _processing_inbound(db, company, lead, text="Ask the team")
    company_id = company.company_id
    lead_id = lead.id
    visitor_id = lead.external_customer_id
    inbound_id = incoming.internal_message_id
    inbound_text = incoming.message

    def accept_once():
        return persist_v2_public_turn_atomic(
            company_id=company_id,
            lead_id=lead_id,
            user_id=visitor_id,
            customer_text=inbound_text,
            assistant_text="Reply",
            inbound_internal_id=inbound_id,
            processing_claim_attempt=1,
            lead_update=None,
            decision=None,
            sales_snapshot=None,
            conversation_action={"type": "ACCEPT_OWNER_VERIFICATION", "status": "executed"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in (pool.submit(accept_once), pool.submit(accept_once))]

    db.expire_all()
    assert sum(result is not None for result in results) == 1
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 1
    actions = db.query(LeadEvent).filter(LeadEvent.lead_id == lead_id).all()
    assert len(actions) == 1
    assert actions[0].event_type == "conversation_action:ACCEPT_OWNER_VERIFICATION"
