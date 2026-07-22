from database import Company, CompanyKnowledge, Lead, LeadEvidence, Message, hash_api_key, save_message
from services.evidence_engine import extract_evidence_from_text


class _FailingCompletions:
    async def create(self, *args, **kwargs):
        raise RuntimeError("simulated provider outage")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingGroq:
    chat = _FailingChat()


def _seed_company(db, company_id="evidence_co", products_data=""):
    company = Company(
        company_id=company_id,
        company_name="Evidence Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a sales assistant.",
            products_data=products_data,
            knowledge_base="",
        )
    )
    db.commit()
    return company


def _types(text, product_names=None):
    return {item.evidence_type for item in extract_evidence_from_text(text, product_names=product_names)}


def test_price_question_extraction_from_arabic_text():
    evidence_types = _types("السعر كام؟")
    assert "price_question" in evidence_types


def test_price_question_extraction_from_english_text():
    evidence_types = _types("What is the price?")
    assert "price_question" in evidence_types


def test_buying_signal_extraction():
    evidence_types = _types("Please send details.")
    assert "buying_signal" in evidence_types


def test_objection_price_extraction():
    evidence_types = _types("This is expensive. Any discount?")
    assert "objection_price" in evidence_types


def test_hesitation_extraction():
    evidence_types = _types("I will think and reply later.")
    assert "hesitation" in evidence_types


def test_urgency_extraction():
    evidence_types = _types("I need this ASAP today.")
    assert "urgency" in evidence_types


def test_product_mention_only_appears_for_known_product():
    evidence_types = _types("Is Demo Product available?", product_names=["Demo Product"])
    assert "product_mention" in evidence_types

    unknown_types = _types("Is Mystery Product available?", product_names=["Demo Product"])
    assert "product_mention" not in unknown_types


def test_duplicate_processing_does_not_duplicate_evidence(db):
    from services.evidence_engine import persist_evidence_for_message

    company = _seed_company(db, company_id="evidence_duplicate")
    save_message(db, company.company_id, "201001112223@s.whatsapp.net", "user", "What is the price?", "msg-evidence-dup", "incoming")

    msg = db.query(Message).filter(Message.internal_message_id == "msg-evidence-dup").one()
    first_count = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == "msg-evidence-dup").count()

    persist_evidence_for_message(db, msg)
    db.commit()

    second_count = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == "msg-evidence-dup").count()
    assert first_count == 1
    assert second_count == first_count


def test_evidence_contains_source_message_ids(db):
    company = _seed_company(db, company_id="evidence_source_ids")
    save_message(db, company.company_id, "201001112223@s.whatsapp.net", "user", "Cost?", "msg-evidence-source", "incoming")

    msg = db.query(Message).filter(Message.internal_message_id == "msg-evidence-source").one()
    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == "msg-evidence-source").one()

    assert evidence.message_id == msg.id
    assert evidence.message_internal_id == msg.internal_message_id
    assert evidence.source == "message"


def test_extraction_does_not_invent_price_or_deal_value(db):
    company = _seed_company(db, company_id="evidence_no_fake_value")
    save_message(db, company.company_id, "201001112223@s.whatsapp.net", "user", "What is the price?", "msg-evidence-price-only", "incoming")

    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == "msg-evidence-price-only").one()
    lead = db.query(Lead).filter(Lead.company_id == company.company_id).first()

    assert evidence.evidence_type == "price_question"
    assert evidence.normalized_value is None
    assert lead is None or lead.opportunity_value is None


def test_inbound_chat_flow_persists_evidence(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    company = _seed_company(db, company_id="evidence_chat_flow")
    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    response = client.post(
        "/chat",
        json={"message": "What is the price?", "user_id": "201001112223@s.whatsapp.net", "external_message_id": "wamid.evidence-chat-1"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company.company_id},
    )

    assert response.status_code == 200
    assert response.json()["reply"]

    incoming = db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "incoming").one()
    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == incoming.internal_message_id).one()
    lead = db.query(Lead).filter(Lead.company_id == company.company_id).one()

    assert evidence.evidence_type == "price_question"
    assert evidence.lead_id == lead.id
    assert evidence.message_id == incoming.id


def test_chat_duplicate_external_message_id_does_not_duplicate_evidence(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    company = _seed_company(db, company_id="evidence_chat_duplicate")
    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    payload = {
        "message": "How can I start? What is the price?",
        "user_id": "201001112223@s.whatsapp.net",
        "external_message_id": "wamid.evidence-dup-1",
    }
    headers = {"X-Internal-Secret": "secret", "X-Company-ID": company.company_id}

    first = client.post("/chat", json=payload, headers=headers)
    second = client.post("/chat", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    incoming = db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "incoming").one()
    lead = db.query(Lead).filter(Lead.company_id == company.company_id).one()
    evidence_rows = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == incoming.internal_message_id).all()
    assert len(evidence_rows) == 2
    assert {row.lead_id for row in evidence_rows} == {lead.id}


def test_unassigned_evidence_can_be_linked_after_lead_creation(db):
    from services.evidence_engine import link_unassigned_evidence_for_lead

    company = _seed_company(db, company_id="evidence_backfill")
    user_id = "201001112223@s.whatsapp.net"
    save_message(db, company.company_id, user_id, "user", "What is the price?", "msg-evidence-backfill", "incoming")

    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == "msg-evidence-backfill").one()
    assert evidence.lead_id is None

    lead = Lead(
        company_id=company.company_id,
        name="Backfill Customer",
        phone="1001112223",
        whatsapp_number="1001112223",
        interest="General",
    )
    db.add(lead)
    db.commit()

    linked_count = link_unassigned_evidence_for_lead(db, company.company_id, lead.id, user_id)
    db.commit()

    db.refresh(evidence)
    assert linked_count == 1
    assert evidence.lead_id == lead.id


def test_evidence_linking_does_not_cross_companies(db):
    from services.evidence_engine import link_unassigned_evidence_for_lead

    company_a = _seed_company(db, company_id="evidence_company_a")
    company_b = _seed_company(db, company_id="evidence_company_b")
    user_id = "201001112223@s.whatsapp.net"

    save_message(db, company_a.company_id, user_id, "user", "What is the price?", "msg-evidence-company-a", "incoming")
    evidence = db.query(LeadEvidence).filter(LeadEvidence.company_id == company_a.company_id).one()
    assert evidence.lead_id is None

    lead_b = Lead(
        company_id=company_b.company_id,
        name="Company B Customer",
        phone="1001112223",
        whatsapp_number="1001112223",
        interest="General",
    )
    db.add(lead_b)
    db.commit()

    linked_count = link_unassigned_evidence_for_lead(db, company_b.company_id, lead_b.id, user_id)
    db.commit()

    db.refresh(evidence)
    assert linked_count == 0
    assert evidence.lead_id is None
