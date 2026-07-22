import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jose import jwt

from database import Message, SystemEvent, WorkspaceSuggestedReply
from services.workspace_suggestion_service import regenerate_workspace_suggestion_variants
from tests.test_velor_chat_mvp import _seed_company, _seed_lead, _seed_message


def _token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_fallback_regeneration_stores_one_contextual_variant_and_never_sends(db, monkeypatch):
    company = _seed_company(db, products_data='[{"name":"Demo Product","price":500,"currency":"EGP"}]')
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    result = await regenerate_workspace_suggestion_variants(db, company.company_id, lead.id)

    assert result["response_path"] == "FALLBACK"
    assert len(result["variants"]) == 1
    assert result["variants"][0]["style"] == "natural"
    assert result["answers_message_id"] == message.id
    assert result["context_version"].endswith(message.internal_message_id)
    assert db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.lead_id == lead.id).count() == 1
    assert db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "outgoing").count() == 0


def test_regenerate_endpoint_is_tenant_scoped_and_returns_variant_contract(client, db, monkeypatch):
    company = _seed_company(db, products_data='[{"name":"Demo Product","price":500,"currency":"EGP"}]')
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "Tell me about Demo Product")
    other = _seed_company(db)
    company_id = company.company_id
    other_company_id = other.company_id
    lead_id = lead.id
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    denied = client.post(
        f"/api/v1/crm/customers/{lead_id}/suggested-replies/regenerate",
        cookies={"access_token": _token(other_company_id)},
    )
    assert denied.status_code == 409

    response = client.post(
        f"/api/v1/crm/customers/{lead_id}/suggested-replies/regenerate",
        cookies={"access_token": _token(company_id)},
    )
    assert response.status_code == 200
    payload = response.json()["suggested_reply"]
    assert payload["variants"]
    assert payload["stale_status"] is False
    assert "fact_ids_used" in payload
    assert "suggested_reply" not in json.dumps(denied.json()).casefold()


def test_regenerate_rejects_an_already_answered_customer_turn(client, db, monkeypatch):
    company = _seed_company(db, products_data='[{"name":"Demo Product","price":500,"currency":"EGP"}]')
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    _seed_message(db, company.company_id, lead, "Demo Product is 500 EGP.", sender="owner")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    response = client.post(
        f"/api/v1/crm/customers/{lead.id}/suggested-replies/regenerate",
        cookies={"access_token": _token(company.company_id)},
    )

    assert response.status_code == 409
    assert db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.lead_id == lead.id,
    ).count() == 0


@pytest.mark.asyncio
async def test_model_regeneration_receives_bounded_context_and_returns_goal_signals(db, monkeypatch):
    company = _seed_company(db, products_data='[{"name":"Chair","price":500,"currency":"EGP"}]')
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "I need something within 700 EGP")
    _seed_message(db, company.company_id, lead, "Chair may fit. What would you like to know?", sender="assistant")
    latest = _seed_message(db, company.company_id, lead, "What is the price for Chair?")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_workspace_context_test_key_123456")

    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        instructions = json.loads(kwargs["messages"][0]["content"])
        price_fact = next(item for item in instructions["allowed_facts"] if item["type"] == "price")
        fact_ids = [price_fact["fact_id"]]
        payload = {
            "variants": [
                {
                    "style": "natural",
                    "text": "Chair price is 500 EGP. Would you like to continue?",
                    "fact_ids_used": fact_ids,
                },
                {
                    "style": "concise",
                    "text": "The price of Chair is 500 EGP.",
                    "fact_ids_used": fact_ids,
                },
                {
                    "style": "commercially_helpful",
                    "text": "Chair price is 500 EGP. What quantity do you need?",
                    "fact_ids_used": fact_ids,
                },
            ]
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    provider_create = AsyncMock(side_effect=create)
    provider = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=provider_create))
    )
    monkeypatch.setattr("services.velor_chat_v2._get_groq_client", lambda: provider)

    result = await regenerate_workspace_suggestion_variants(db, company.company_id, lead.id)

    assert result["response_path"] == "MODEL"
    assert result["source_message_internal_id"] == latest.internal_message_id
    assert provider_create.await_count == 1
    provider_messages = captured["messages"]
    instructions = json.loads(provider_messages[0]["content"])
    assert instructions["conversation_brief"]["objective"]
    assert "customer_memory" in instructions
    assert "communication_policy" in instructions
    assert len(instructions["variant_blueprints"]) == 3
    assert any(message["content"] == "I need something within 700 EGP" for message in provider_messages)
    assert any(message["role"] == "assistant" and "What would you like to know?" in message["content"] for message in provider_messages)
    assert provider_messages[-1] == {"role": "user", "content": latest.message}
    assert {variant["style"] for variant in result["variants"]} == {
        "natural",
        "concise",
        "commercially_helpful",
    }
    assert all(variant["goal"] for variant in result["variants"])
    assert all(variant["context_signals"]["history_turn_count"] >= 2 for variant in result["variants"])


@pytest.mark.asyncio
async def test_regeneration_discards_provider_result_when_owner_replies_during_await(db, monkeypatch):
    company = _seed_company(db, products_data='[{"name":"Chair","price":500,"currency":"EGP"}]')
    lead = _seed_lead(db, company.company_id)
    latest = _seed_message(db, company.company_id, lead, "What is the price for Chair?")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_workspace_race_test_key_123456")

    async def create(**kwargs):
        instructions = json.loads(kwargs["messages"][0]["content"])
        price_fact = next(item for item in instructions["allowed_facts"] if item["type"] == "price")
        db.add(
            Message(
                company_id=company.company_id,
                user_id=latest.user_id,
                sender="owner",
                direction="outgoing",
                message="I already answered this.",
                internal_message_id="owner-won-regeneration-race",
                delivery_status="sent",
            )
        )
        db.commit()
        variants = [
            {"style": style, "text": text, "fact_ids_used": [price_fact["fact_id"]]}
            for style, text in (
                ("natural", "Chair price is 500 EGP. Would you like to continue?"),
                ("concise", "Chair price is 500 EGP."),
                ("commercially_helpful", "Chair price is 500 EGP. What quantity do you need?"),
            )
        ]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"variants": variants})))]
        )

    provider = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create)))
    )
    monkeypatch.setattr("services.velor_chat_v2._get_groq_client", lambda: provider)

    result = await regenerate_workspace_suggestion_variants(db, company.company_id, lead.id)

    assert result is None
    assert db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company.company_id,
    ).count() == 0
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company.company_id,
        SystemEvent.event_type == "workspace.suggested_reply",
    ).count() == 0
