import asyncio
import uuid

from database import Company, Message, hash_api_key


def _seed_company(db, company_id=None):
    from database import CompanyKnowledge

    company_id = company_id or f"latency_{uuid.uuid4().hex[:8]}"
    company = Company(
        company_id=company_id,
        company_name=f"{company_id} Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
        is_web_chat_enabled=True,
        public_chat_slug=f"{company_id}-slug",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a helpful assistant.",
            products_data="[]",
            welcome_message="Welcome",
            suggested_questions="",
        )
    )
    db.commit()
    db.refresh(company)
    return company


def test_public_chat_timeout_marks_claim_failed_and_retry_reclaims(client, db, monkeypatch):
    import main as api_main

    company = _seed_company(db, "latency_retry")
    session = client.post(f"/api/public/companies/{company.public_chat_slug}/session").json()
    token = session["token"]
    client_message_id = str(uuid.uuid4())
    wa_message_id = f"wc:{company.company_id}:{client_message_id}"

    async def slow_response(**kwargs):
        await asyncio.sleep(0.2)
        return "late reply", None

    monkeypatch.setenv("PUBLIC_CHAT_REPLY_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(api_main, "get_ai_response", slow_response)

    timed_out = client.post(
        "/api/public/chat",
        json={"message": "Hello, I need help", "client_message_id": client_message_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert timed_out.status_code == 504
    db.expire_all()
    incoming = db.query(Message).filter(Message.wa_message_id == wa_message_id, Message.direction == "incoming").one()
    assert incoming.processing_status == "failed"

    async def fast_response(**kwargs):
        return "Recovered reply", None

    monkeypatch.setenv("PUBLIC_CHAT_REPLY_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(api_main, "get_ai_response", fast_response)

    retry = client.post(
        "/api/public/chat",
        json={"message": "Hello, I need help", "client_message_id": client_message_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert retry.status_code == 200
    assert retry.json()["status"] == "completed"
    assert retry.json()["reply"] == "Recovered reply"
    assert db.query(Message).filter(Message.wa_message_id == wa_message_id, Message.direction == "incoming").count() == 1
    db.expire_all()
    assert db.query(Message).filter(Message.wa_message_id == wa_message_id).one().processing_status == "completed"


def test_public_chat_provider_failure_marks_claim_failed_and_retry_reclaims(client, db, monkeypatch):
    import main as api_main

    company = _seed_company(db, "latency_provider_failure")
    session = client.post(f"/api/public/companies/{company.public_chat_slug}/session").json()
    token = session["token"]
    client_message_id = str(uuid.uuid4())
    wa_message_id = f"wc:{company.company_id}:{client_message_id}"

    async def failing_response(**kwargs):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(api_main, "get_ai_response", failing_response)

    failed = client.post(
        "/api/public/chat",
        json={"message": "Hello, I need help", "client_message_id": client_message_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert failed.status_code == 500
    db.expire_all()
    incoming = db.query(Message).filter(Message.wa_message_id == wa_message_id, Message.direction == "incoming").one()
    assert incoming.processing_status == "failed"

    async def recovered_response(**kwargs):
        return "Recovered after provider failure", None

    monkeypatch.setattr(api_main, "get_ai_response", recovered_response)

    retry = client.post(
        "/api/public/chat",
        json={"message": "Hello, I need help", "client_message_id": client_message_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert retry.status_code == 200
    assert retry.json()["status"] == "completed"
    assert retry.json()["reply"] == "Recovered after provider failure"
    assert db.query(Message).filter(Message.wa_message_id == wa_message_id, Message.direction == "incoming").count() == 1
    db.expire_all()
    assert db.query(Message).filter(Message.wa_message_id == wa_message_id).one().processing_status == "completed"
