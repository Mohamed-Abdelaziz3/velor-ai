import ast
import uuid
from collections import Counter
from pathlib import Path

import database
from database import (
    Company,
    Lead,
    Message,
    MessageEvent,
    UsageStats,
    hash_api_key,
    save_lead,
    save_lead_atomic,
    save_message,
)
from engine.intelligence_bus import bus


PERSISTENCE_ENTRY_POINTS = {
    "_upsert_usage_in_session",
    "save_message",
    "save_lead",
    "get_latest_leads",
    "create_company",
    "toggle_lead_pause",
    "is_lead_paused",
}


def _seed_company(db):
    suffix = uuid.uuid4().hex
    company = Company(
        company_id=f"persistence_{suffix[:12]}",
        company_name="Persistence Contract",
        email=f"persistence-{suffix}@example.com",
        password="hashed-for-test",
        api_key_hash=hash_api_key(f"persistence-key-{suffix}"),
        plan="PRO",
    )
    db.add(company)
    db.commit()
    return company


def test_persistence_entry_points_have_one_top_level_definition():
    """A later def must never silently replace an earlier persistence helper."""
    source = Path(database.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    counts = Counter(
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    duplicates = {name: count for name, count in counts.items() if count > 1}

    assert duplicates == {}
    assert PERSISTENCE_ENTRY_POINTS <= counts.keys()


def test_web_chat_lead_upsert_keeps_opaque_identifier(db, monkeypatch):
    monkeypatch.setattr(bus, "publish_sync", lambda _event: None)
    company = _seed_company(db)
    visitor_id = f"wc_v_{uuid.uuid4().hex}"

    created = save_lead_atomic(
        db,
        company.company_id,
        "Web visitor",
        None,
        "first question",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=visitor_id,
    )
    first = (
        db.query(Lead)
        .filter(
            Lead.company_id == company.company_id,
            Lead.channel_type == "VELOR_WEB_CHAT",
            Lead.external_customer_id == visitor_id,
        )
        .one()
    )
    first_id = first.id

    updated = save_lead_atomic(
        db,
        company.company_id,
        "Returning web visitor",
        None,
        "updated question",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=visitor_id,
    )
    db.expire_all()
    rows = (
        db.query(Lead)
        .filter(
            Lead.company_id == company.company_id,
            Lead.channel_type == "VELOR_WEB_CHAT",
            Lead.external_customer_id == visitor_id,
        )
        .all()
    )

    assert created is True
    assert updated is False
    assert len(rows) == 1
    assert rows[0].id == first_id
    assert rows[0].phone is None
    assert rows[0].whatsapp_number is None
    assert rows[0].external_customer_id == visitor_id
    assert rows[0].interest == "updated question"
    usage = db.query(UsageStats).filter(UsageStats.company_id == company.company_id).one()
    assert usage.leads_count == 1


def test_whatsapp_and_message_writes_keep_canonical_identifiers(db, monkeypatch):
    monkeypatch.setattr(bus, "publish_sync", lambda _event: None)
    company = _seed_company(db)
    local_phone = "1012345678"
    whatsapp_number = "201012345678"

    created = save_lead(
        db,
        company.company_id,
        "WhatsApp customer",
        "+20 10 1234 5678",
        "initial interest",
        whatsapp_number=whatsapp_number,
        whatsapp_jid=f"{whatsapp_number}@s.whatsapp.net",
    )
    updated = save_lead(
        db,
        company.company_id,
        "WhatsApp customer",
        "+20 10 1234 5678",
        "updated interest",
        whatsapp_number=whatsapp_number,
        whatsapp_jid=f"{whatsapp_number}@s.whatsapp.net",
    )

    leads = (
        db.query(Lead)
        .filter(
            Lead.company_id == company.company_id,
            Lead.whatsapp_number == whatsapp_number,
        )
        .all()
    )
    assert created is True
    assert updated is False
    assert len(leads) == 1
    assert leads[0].phone == local_phone
    assert leads[0].channel_type == "WHATSAPP_QR"
    assert leads[0].external_customer_id is None
    assert leads[0].interest == "updated interest"

    internal_message_id = f"msg-{uuid.uuid4().hex}"
    provider_message_id = f"wamid.{uuid.uuid4().hex}"
    save_message(
        db,
        company.company_id,
        whatsapp_number,
        "assistant",
        "canonical reply",
        internal_message_id,
        "outgoing",
        wa_message_id=provider_message_id,
        delivery_status="sent",
    )

    message = (
        db.query(Message)
        .filter(Message.internal_message_id == internal_message_id)
        .one()
    )
    db.refresh(leads[0])
    assert message.company_id == company.company_id
    assert message.user_id == whatsapp_number
    assert message.wa_message_id == provider_message_id
    assert message.public_message_id.startswith("pub-")
    assert message.delivery_status == "sent"
    assert (
        db.query(MessageEvent)
        .filter(MessageEvent.message_id == message.id, MessageEvent.status == "sent")
        .count()
        == 1
    )
    assert leads[0].last_message == "canonical reply"
    assert leads[0].conversation_count == 1
    usage = db.query(UsageStats).filter(UsageStats.company_id == company.company_id).one()
    assert usage.leads_count == 1
