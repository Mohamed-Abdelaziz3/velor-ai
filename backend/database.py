"""VELOR production persistence models and transaction helpers.

Alembic is the authoritative schema path. Runtime helpers in this module keep
message, lead, usage, audit, and refresh-token writes transactionally scoped.
"""

import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    DateTime,
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Float,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker, joinedload
from sqlalchemy.sql import func
from sqlalchemy import create_engine
from passlib.context import CryptContext
from schema_verification import (
    assert_schema_compatible as _assert_schema_compatible,
    database_target_for_log,
    resolve_database_url,
    schema_status as _schema_status,
)

load_dotenv()
log = logging.getLogger("adam.db")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ─────────────────────────────────────────────────
# 🔒 SECURITY
# ─────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_DUMMY_HASH: str = pwd_context.hash("__dummy_timing_protection__")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def timing_safe_verify(plain: str, hashed: Optional[str]) -> bool:
    """Always runs bcrypt — prevents timing-based user enumeration."""
    return pwd_context.verify(plain, hashed if hashed else _DUMMY_HASH)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    return f"adam_live_{secrets.token_urlsafe(48)}"


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


# ─────────────────────────────────────────────────
# 📦 ENGINE
# ─────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
_DATABASE_URL: str = resolve_database_url(
    os.getenv("DATABASE_URL", "sqlite:///adam_ai.db"),
    BACKEND_DIR,
)

if _DATABASE_URL.startswith("sqlite"):
    if ":memory:" in _DATABASE_URL or _DATABASE_URL == "sqlite://" or _DATABASE_URL == "sqlite:///":
        engine = create_engine(
            _DATABASE_URL,
            connect_args={"check_same_thread": False},
        )
    else:
        sqlite_pool_size = int(os.getenv("SQLITE_POOL_SIZE", "32"))
        sqlite_max_overflow = int(os.getenv("SQLITE_MAX_OVERFLOW", "16"))
        sqlite_pool_timeout = int(os.getenv("SQLITE_POOL_TIMEOUT", "30"))
        
        # Enforce that pool parameters cannot be excessively large to prevent resource exhaustion
        if sqlite_pool_size > 100 or sqlite_max_overflow > 200:
            raise ValueError("SQLITE_POOL_SIZE cannot exceed 100 and SQLITE_MAX_OVERFLOW cannot exceed 200")
            
        engine = create_engine(
            _DATABASE_URL,
            connect_args={"check_same_thread": False},
            pool_size=sqlite_pool_size,
            max_overflow=sqlite_max_overflow,
            pool_timeout=sqlite_pool_timeout,
        )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=5000;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.close()

else:
    # pool_size should match the number of concurrent DB-bound requests
    # For uvicorn with 1 worker, 5 is sufficient; scale with workers count.
    engine = create_engine(
        _DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_database_runtime_summary(*, require_migration_head: bool) -> Dict[str, Any]:
    """Safe runtime health information; never includes credentials."""
    status = _schema_status(
        engine,
        Base.metadata,
        BACKEND_DIR,
        require_migration_head=require_migration_head,
    )
    return {
        **status,
        "database_dialect": engine.dialect.name,
        "database_target": database_target_for_log(_DATABASE_URL),
    }


def assert_database_schema_compatible(*, require_migration_head: bool) -> Dict[str, Any]:
    status = _assert_schema_compatible(
        engine,
        Base.metadata,
        BACKEND_DIR,
        require_migration_head=require_migration_head,
    )
    return {
        **status,
        "database_dialect": engine.dialect.name,
        "database_target": database_target_for_log(_DATABASE_URL),
    }

# Dialect-aware INSERT for true UPSERT in save_lead_atomic
if _DATABASE_URL.startswith("sqlite"):
    from sqlalchemy.dialects.sqlite import insert as _dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as _dialect_insert


# ─────────────────────────────────────────────────
# 🏗️ AUDIT MIXIN
# ─────────────────────────────────────────────────
class AuditMixin:
    uuid = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ─────────────────────────────────────────────────
# 🗄️ MODELS
# ─────────────────────────────────────────────────


class Company(Base, AuditMixin):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), unique=True, index=True, nullable=False)
    company_name = Column(String(200), nullable=False)
    email = Column(String(254), unique=True, index=True, nullable=False)
    password = Column(String(256), nullable=False)
    api_key_hash = Column(String(64), unique=True, index=True, nullable=False)
    role = Column(String(20), default="tenant", nullable=False)
    auth_provider = Column(String(20), default="password", server_default="password", nullable=False)
    google_subject = Column(String(255), unique=True, index=True, nullable=True)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    terms_version = Column(String(40), nullable=True)
    privacy_version = Column(String(40), nullable=True)
    plan = Column(
        SAEnum("FREE", "PRO", "ENTERPRISE", name="company_plan"),
        default="FREE",
        nullable=False,
    )
    is_alerts_enabled = Column(Boolean, default=False, nullable=False)
    alert_whatsapp_number = Column(String(20), nullable=True)
    bot_auto_reply_enabled = Column(Boolean, default=True, nullable=False)
    daily_sales_target = Column(Integer, default=5, nullable=False)
    is_web_chat_enabled = Column(Boolean, default=False, server_default="0", nullable=False)
    public_chat_slug = Column(String(100), unique=True, index=True, nullable=True)

    # Composite indexes for the two hot-path lookups
    __table_args__ = (
        Index("ix_company_api_deleted", "api_key_hash", "is_deleted"),
        Index("ix_company_email_deleted", "email", "is_deleted"),
    )

    leads = relationship("Lead", back_populates="company", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="company", cascade="all, delete-orphan")
    knowledge = relationship("CompanyKnowledge", back_populates="company", uselist=False, cascade="all, delete-orphan")
    usage = relationship("UsageStats", back_populates="company", uselist=False, cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="company", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="company", cascade="all, delete-orphan")


class CompanyKnowledge(Base, AuditMixin):
    __tablename__ = "company_knowledge"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), unique=True, index=True)
    system_prompt = Column(Text, nullable=False, default="أنت مساعد مبيعات محترف.")
    products_data = Column(Text, nullable=False, default="")
    google_sheet_webhook_url = Column(String(500), nullable=True, default=None)

    welcome_message = Column(Text, nullable=True, default="")
    suggested_questions = Column(Text, nullable=True, default="")
    knowledge_base = Column(Text, nullable=True, default="")
    industry = Column(String(200), nullable=True, default="")
    language = Column(String(50), nullable=True, default="Arabic")
    tone = Column(String(50), nullable=True, default="Professional")
    lead_collection = Column(Boolean, nullable=False, default=True)

    company = relationship("Company", back_populates="knowledge")


class KnowledgeSource(Base, AuditMixin):
    """Tenant-scoped, reviewable source used by bounded knowledge retrieval.

    Uploaded bytes are not retained.  The extracted text is kept so disabling,
    re-enabling, and deleting a source can update the compiled legacy knowledge
    field without pretending an unusable upload is active.
    """

    __tablename__ = "knowledge_sources"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True, nullable=False)
    source_name = Column(String(160), nullable=False)
    source_type = Column(String(30), nullable=False)
    mime_type = Column(String(120), nullable=True)
    status = Column(String(30), nullable=False, default="processed", index=True)
    extracted_text = Column(Text, nullable=False)
    extracted_char_count = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True, index=True)
    error_category = Column(String(80), nullable=True)
    last_processed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    company = relationship("Company")

    __table_args__ = (
        Index("ix_knowledge_source_company_active_updated", "company_id", "active", "updated_at"),
    )


class Lead(Base, AuditMixin):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20), index=True, nullable=True)
    whatsapp_number = Column(String(20), index=True, nullable=True)
    whatsapp_jid = Column(String(100), nullable=True)
    customer_provided_phone = Column(String(20), nullable=True)
    interest = Column(Text)
    channel_type = Column(String(50), default="WHATSAPP_QR", server_default="WHATSAPP_QR", nullable=False)
    external_customer_id = Column(String(100), nullable=True)
    is_paused = Column(Boolean, default=False, nullable=False)
    temperature = Column(String(10), default="cold")  # Backward-compatible temperature field
    lead_score = Column(Integer, default=0, nullable=False)
    status = Column(String(50), default="new", nullable=False)
    ai_summary = Column(Text, nullable=True)
    last_message_preview = Column(Text, nullable=True)
    last_message = Column(Text, nullable=True)
    last_message_sender = Column(String(50), nullable=True)
    conversation_count = Column(Integer, default=0, nullable=False)
    first_contact_date = Column(DateTime(timezone=True), server_default=func.now())
    last_contact_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    summary = Column(Text, nullable=True)
    intent_score = Column(Float, nullable=True)
    is_hot_deal = Column(Boolean, default=False, nullable=False)
    needs_human_intervention = Column(Boolean, default=False, nullable=False)
    opportunity_value = Column(Float, nullable=True)
    stage = Column(String(100), server_default="Information Gathering", nullable=False)
    stage_updated_at = Column(DateTime(timezone=True), server_default=func.now())
    conversation_state = Column(String(50), default="GREETING", server_default="GREETING", nullable=False)
    pending_question = Column(Text, nullable=True)
    is_test = Column(Boolean, default=False, server_default="0", nullable=False)

    # CRM Enhancements
    customer_health = Column(String(50), nullable=True, default="Good")
    tags = Column(Text, nullable=True, default="[]")
    sales_state_snapshot = Column(Text, nullable=True)

    company = relationship("Company", back_populates="leads")
    intelligence_snapshot = relationship("LeadIntelligenceSnapshot", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    events = relationship("LeadEvent", back_populates="lead", cascade="all, delete-orphan")
    signals = relationship("LeadSignal", back_populates="lead", cascade="all, delete-orphan")
    evidence_items = relationship("LeadEvidence", back_populates="lead", cascade="all, delete-orphan")
    follow_up_tasks = relationship("FollowUpTask", back_populates="lead", cascade="all, delete-orphan")
    memory = relationship("LeadMemory", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    analytics = relationship("LeadAnalytics", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    notes = relationship("CustomerNote", back_populates="lead", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="lead", cascade="all, delete-orphan")
    suggested_replies = relationship("WorkspaceSuggestedReply", back_populates="lead", cascade="all, delete-orphan")
    commercial_decisions = relationship("CommercialDecisionLineage", back_populates="lead", cascade="all, delete-orphan")
    commercial_events = relationship("CommercialEvent", back_populates="lead", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "phone", name="_company_phone_uc"),
        UniqueConstraint("company_id", "whatsapp_number", name="_company_whatsapp_uc"),
        UniqueConstraint("company_id", "channel_type", "external_customer_id", name="_company_channel_customer_uc"),
        # Covering index for save_lead_atomic existence check
        Index("ix_lead_company_phone_deleted", "company_id", "phone", "is_deleted"),
        Index("ix_lead_company_whatsapp_deleted", "company_id", "whatsapp_number", "is_deleted"),
    )


class CustomerNote(Base):
    __tablename__ = "customer_notes"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=True, default="System")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lead = relationship("Lead", back_populates="notes")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    action_type = Column(String(100), nullable=False)  # Backward-compatible free-text action
    event_type = Column(String(50), nullable=True, default="activity")  # Structured event type (e.g. MESSAGE, NOTE, PROPOSAL)
    description = Column(Text, nullable=True)
    metadata_payload = Column(Text, nullable=True)  # JSON object for structured UI metadata
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    lead = relationship("Lead", back_populates="activity_logs")


def normalize_whatsapp_number(user_id: str) -> str:

    if not user_id:
        return ""
    # If it contains letters and is not a WhatsApp JID, treat it as a generic opaque identifier
    if any(c.isalpha() for c in user_id) and not (user_id.endswith("@s.whatsapp.net") or user_id.endswith("@lid") or user_id.endswith("@g.us")):
        return user_id
    clean_phone = re.sub(r"\D", "", user_id)
    if clean_phone.startswith("201") and len(clean_phone) >= 12:
        return clean_phone[2:]
    elif clean_phone.startswith("01") and len(clean_phone) >= 11:
        return clean_phone[1:]
    return clean_phone


def get_phone_variants(phone: str) -> list:

    if not phone:
        return []
    clean_phone = re.sub(r"\D", "", phone)

    base_phone = clean_phone
    if clean_phone.startswith("201") and len(clean_phone) >= 12:
        base_phone = clean_phone[2:]
    elif clean_phone.startswith("01") and len(clean_phone) >= 11:
        base_phone = clean_phone[1:]

    return [
        base_phone,
        f"0{base_phone}",
        f"20{base_phone}",
        f"+20{base_phone}",
        f"{base_phone}@s.whatsapp.net",
        f"20{base_phone}@s.whatsapp.net",
        f"{base_phone}@c.us",
        f"{base_phone}@lid",
    ]


def get_live_leads_filter(Lead):
    """
    Returns a SQLAlchemy filter condition that excludes test leads.
    Strictly uses the explicit `is_test` boundary.
    """
    from sqlalchemy import not_

    return not_(Lead.is_test == True)


class LeadMemory(Base, AuditMixin):
    __tablename__ = "lead_memory"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True, unique=True)
    customer_summary = Column(Text, nullable=True)
    product_interest = Column(Text, nullable=True)
    budget = Column(Text, nullable=True)
    preferences = Column(Text, nullable=True)
    purchase_history = Column(Text, nullable=True)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_memory_rebuild_at = Column(DateTime(timezone=True), nullable=True)

    lead = relationship("Lead", back_populates="memory")


class LeadAnalytics(Base, AuditMixin):
    __tablename__ = "lead_analytics"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True, unique=True)
    top_requested_products = Column(Text, nullable=True)  # Stored as JSON string
    trending_topics = Column(Text, nullable=True)  # Stored as JSON string
    business_opportunity = Column(Text, nullable=True)
    last_analyzed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lead = relationship("Lead", back_populates="analytics")


class Message(Base, AuditMixin):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    internal_message_id = Column(String(64), unique=True, index=True, nullable=False)
    public_message_id = Column(String(64), unique=True, index=True, nullable=True)
    wa_message_id = Column(String(128), unique=True, index=True, nullable=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True)
    user_id = Column(String(100), index=True, nullable=False)
    sender = Column(String(20), nullable=False)
    direction = Column(String(20), nullable=False)  # incoming / outgoing
    message = Column(Text, nullable=False)
    delivery_status = Column(String(20), default="pending", nullable=False)
    processing_status = Column(String(30), default="completed", nullable=False, index=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_attempts = Column(Integer, default=0, nullable=False)
    # Canonical one-to-one reply linkage.  This removes the unsafe legacy
    # heuristic that guessed a reply by selecting the next outgoing row.
    in_reply_to_message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    company = relationship("Company", back_populates="messages")
    events = relationship("MessageEvent", back_populates="message_obj", cascade="all, delete-orphan")
    evidence_items = relationship("LeadEvidence", back_populates="message_obj", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_msg_company_user_ts", "company_id", "user_id", "created_at"),)


class MessageEvent(Base):
    __tablename__ = "message_events"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    status = Column(String(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    message_obj = relationship("Message", back_populates="events")


class WebhookInbox(Base):
    """Durable provider-webhook ingress before asynchronous processing."""

    __tablename__ = "webhook_inbox"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(30), nullable=False, index=True)
    payload_hash = Column(String(64), nullable=False, unique=True, index=True)
    provider_event_id = Column(String(128), nullable=True, index=True)
    company_id = Column(
        String(64),
        ForeignKey("companies.company_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload_json = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error_category = Column(String(120), nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_webhook_inbox_status_created", "status", "created_at"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Covering index for token-validation query
    __table_args__ = (Index("ix_rt_active_lookup", "token_hash", "revoked", "expires_at"),)

    company = relationship("Company", back_populates="refresh_tokens")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(300), nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    company = relationship("Company", back_populates="audit_logs")


class UsageStats(Base):
    __tablename__ = "usage_stats"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), unique=True, index=True)
    messages_count = Column(Integer, default=0, nullable=False)
    leads_count = Column(Integer, default=0, nullable=False)
    requests_count = Column(Integer, default=0, nullable=False)
    # month tracking for plan enforcement
    current_month = Column(String(7), default=lambda: datetime.now(timezone.utc).strftime("%Y-%m"), nullable=False)
    monthly_messages = Column(Integer, default=0, nullable=False)
    monthly_leads = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="usage")


class SystemEvent(Base, AuditMixin):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True)
    event_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(128), nullable=True, index=True)
    idempotency_key = Column(String(160), nullable=True)
    payload = Column(Text, nullable=False)
    processed = Column(Boolean, default=False, index=True)

    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "event_type",
            "idempotency_key",
            name="uq_system_event_company_type_idempotency",
        ),
        Index("ix_system_event_company_type_created", "company_id", "event_type", "created_at"),
    )


class LeadEvent(Base):
    __tablename__ = "lead_events"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    event_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    lead = relationship("Lead", back_populates="events")


class LeadSignal(Base):
    __tablename__ = "lead_signals"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    signal_category = Column(String(100), nullable=False)
    score_modifier = Column(Integer, nullable=False)
    reasoning = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    lead = relationship("Lead", back_populates="signals")


class LeadEvidence(Base):
    __tablename__ = "lead_evidence"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True)
    message_internal_id = Column(String(64), index=True, nullable=False)
    evidence_type = Column(String(100), index=True, nullable=False)
    source = Column(String(50), default="message", nullable=False)
    source_text = Column(Text, nullable=False)
    normalized_value = Column(Text, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    metadata_json = Column(Text, nullable=True)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    lead = relationship("Lead", back_populates="evidence_items")
    message_obj = relationship("Message", back_populates="evidence_items")
    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint("company_id", "message_internal_id", "evidence_type", "evidence_hash", name="uq_lead_evidence_message_type_hash"),
        Index("ix_lead_evidence_company_type_created", "company_id", "evidence_type", "created_at"),
    )


class WorkspaceSuggestedReply(Base):
    __tablename__ = "workspace_suggested_replies"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    source_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True)
    source_message_internal_id = Column(String(64), index=True, nullable=False)
    suggested_reply = Column(Text, nullable=False)
    why_this_reply = Column(Text, nullable=True)
    evidence_summary = Column(Text, nullable=True)
    missing_data = Column(Text, nullable=True, default="[]")
    style = Column(String(40), nullable=False, default="natural")
    context_version = Column(String(40), nullable=False, default="v2")
    fact_ids_used = Column(Text, nullable=False, default="[]")
    variants_json = Column(Text, nullable=False, default="[]")
    stale_reason = Column(String(80), nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String(30), default="suggested", nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lead = relationship("Lead", back_populates="suggested_replies")
    message_obj = relationship("Message")
    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint("company_id", "source_message_internal_id", name="uq_workspace_suggestion_source_message"),
        Index("ix_workspace_suggestions_lead_status_created", "lead_id", "status", "created_at"),
    )


class CommercialDecisionLineage(Base):
    """Structured commercial decisions and later observations; never private reasoning."""

    __tablename__ = "commercial_decision_lineage"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    source_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True)
    source_message_internal_id = Column(String(64), index=True, nullable=False)
    objective = Column(String(80), index=True, nullable=False)
    strategy = Column(String(80), index=True, nullable=False)
    next_move = Column(String(80), nullable=False)
    decision_json = Column(Text, nullable=False)
    evidence_json = Column(Text, nullable=False, default="[]")
    escalation_required = Column(Boolean, nullable=False, default=False, index=True)
    escalation_json = Column(Text, nullable=True)
    observed_outcome = Column(String(80), nullable=True, index=True)
    outcome_evidence_json = Column(Text, nullable=True)
    outcome_observed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    lead = relationship("Lead", back_populates="commercial_decisions")
    company = relationship("Company")
    source_message = relationship("Message")

    __table_args__ = (
        UniqueConstraint("company_id", "source_message_internal_id", name="uq_commercial_decision_source_message"),
        Index("ix_commercial_decision_company_created", "company_id", "created_at"),
        Index("ix_commercial_decision_lead_created", "lead_id", "created_at"),
    )


class CommercialEvent(Base):
    """Deterministic business-level event derived from traceable conversation evidence."""

    __tablename__ = "commercial_events"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True)
    source_message_internal_id = Column(String(64), index=True, nullable=False)
    channel = Column(String(50), nullable=False)
    event_type = Column(String(80), index=True, nullable=False)
    product_ref = Column(String(240), index=True, nullable=True)
    stage = Column(String(80), index=True, nullable=True)
    objection_type = Column(String(80), index=True, nullable=True)
    source_text = Column(Text, nullable=False)
    evidence_json = Column(Text, nullable=False, default="{}")
    provenance = Column(String(80), nullable=False, default="deterministic_v1")
    event_hash = Column(String(64), nullable=False)
    observed_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    lead = relationship("Lead", back_populates="commercial_events")
    company = relationship("Company")
    message_obj = relationship("Message")

    __table_args__ = (
        UniqueConstraint("company_id", "event_hash", name="uq_commercial_event_hash"),
        Index("ix_commercial_event_company_type_observed", "company_id", "event_type", "observed_at"),
        Index("ix_commercial_event_company_product_observed", "company_id", "product_ref", "observed_at"),
        Index("ix_commercial_event_lead_observed", "lead_id", "observed_at"),
    )


class LeadIntelligenceSnapshot(Base):
    __tablename__ = "lead_intelligence_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), unique=True, index=True)
    priority_score = Column(Integer, default=0, nullable=False)
    confidence_score = Column(Integer, default=0, nullable=False)
    lost_risk_score = Column(Integer, default=0, nullable=False)
    next_best_action = Column(Text, nullable=True)
    action_reason = Column(Text, nullable=True)
    why_summary = Column(Text, nullable=True)
    why_here = Column(Text, nullable=True)
    why_matter = Column(Text, nullable=True)
    expected_outcome = Column(Text, nullable=True)
    execution_sequence = Column(Text, nullable=True)  # Stored as JSON string array
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lead = relationship("Lead", back_populates="intelligence_snapshot")


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    task_level = Column(Integer, default=1, nullable=False)
    task_type = Column(String(100), nullable=False)
    source_type = Column(String(50), nullable=False, default="owner_attention_projection")
    source_identifier = Column(String(160), nullable=False)
    source_event_id = Column(Integer, ForeignKey("commercial_events.id", ondelete="SET NULL"), nullable=True, index=True)
    source_message_internal_id = Column(String(64), nullable=True, index=True)
    reason_code = Column(String(100), nullable=False)
    idempotency_key = Column(String(160), nullable=False)
    category = Column(String(50), nullable=False, default="FOLLOW_UP_DUE")
    priority = Column(Integer, nullable=False, default=50)
    status = Column(String(50), default="pending", nullable=False, index=True)
    due_at = Column(DateTime(timezone=True), nullable=False)
    suggested_message = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    completion_reference = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    lead = relationship("Lead", back_populates="follow_up_tasks")
    company = relationship("Company")
    source_event = relationship("CommercialEvent")

    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_follow_up_company_idempotency"),
        Index("ix_follow_up_company_status_due", "company_id", "status", "due_at"),
        Index("ix_follow_up_company_lead_status", "company_id", "lead_id", "status"),
    )


# ─────────────────────────────────────────────────
# ♻️ FastAPI DB DEPENDENCY
# ─────────────────────────────────────────────────
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─────────────────────────────────────────────────
# 💾 ATOMIC WRITE HELPERS  (Issue #1)
# ─────────────────────────────────────────────────


def save_message_and_increment_atomic(
    db: Session,
    company_id: str,
    user_id: str,
    sender: str,
    message: str,
    internal_message_id: str,
    direction: str,
    wa_message_id: str = None,
    delivery_status: str = "pending",
) -> None:
    """
    #1 — ATOMIC: Message row + UsageStats update in ONE transaction.
    If anything fails the whole unit rolls back — no orphaned counters.
    """
    try:
        msg_obj = Message(
            internal_message_id=internal_message_id,
            public_message_id=f"pub-{uuid.uuid4().hex}",
            wa_message_id=wa_message_id,
            company_id=company_id,
            user_id=user_id,
            sender=sender,
            direction=direction,
            message=message,
            delivery_status=delivery_status,
        )
        db.add(msg_obj)
        db.flush()

        live_event_type = "message.received" if sender == "user" else "message.sent"

        # Add initial event
        db.add(MessageEvent(message_id=msg_obj.id, status=delivery_status))

        import json

        event_payload = json.dumps(
            {
                "message_id": internal_message_id,
                "wa_message_id": wa_message_id,
                "sender": sender,
                "direction": direction,
                "text": message,
                "user_id": user_id,
                "delivery_status": delivery_status,
                "timestamp": msg_obj.created_at.isoformat() if msg_obj.created_at else datetime.now(timezone.utc).isoformat(),
            }
        )
        db.add(SystemEvent(company_id=company_id, event_type="message.created", entity_id=internal_message_id, payload=event_payload))
        db.add(SystemEvent(company_id=company_id, event_type=live_event_type, entity_id=internal_message_id, payload=event_payload))

        # 2. Increment usage counters (only for incoming user messages)
        if sender == "user":
            _upsert_usage_in_session(db, company_id, messages=1, requests=1)

        # 3. Update corresponding Lead row with new message data
        base_phone = normalize_whatsapp_number(user_id)

        lead = (
            db.query(Lead)
            .filter(
                Lead.company_id == company_id,
                (Lead.whatsapp_number == base_phone) | (Lead.phone.in_(get_phone_variants(base_phone))),
                Lead.is_deleted == False,
            )
            .first()
        )
        if lead:
            lead.last_message = message
            lead.last_message_sender = sender
            lead.conversation_count = (lead.conversation_count or 0) + 1
            lead.last_contact_date = func.now()

        # Evidence Engine MVP: best-effort deterministic extraction for inbound customer messages.
        if sender == "user" and direction == "incoming":
            try:
                from services.evidence_engine import persist_evidence_for_message

                persist_evidence_for_message(db, msg_obj)
            except Exception as evidence_exc:
                log.exception("Evidence extraction failed for message %s: %s", internal_message_id, evidence_exc)
            try:
                from services.follow_up_service import supersede_for_new_customer_turn

                supersede_for_new_customer_turn(db, msg_obj, commit=False)
            except Exception as follow_up_exc:
                # Follow-up maintenance must not corrupt durable message intake.
                log.warning(
                    "Follow-up supersede failed message=%s category=%s",
                    internal_message_id,
                    follow_up_exc.__class__.__name__,
                )

        # 4. Single commit — atomic
        db.commit()
        
        # 5. Emit Event to Intelligence Bus
        from engine.intelligence_bus import bus, IntelligenceEvent, EventSeverity
        bus.publish_sync(IntelligenceEvent(
            topic="message.received" if sender == "user" else "message.sent",
            severity=EventSeverity.INFO,
            company_id=company_id,
            payload={
                "message_id": internal_message_id,
                "sender": sender,
                "text": message,
                "user_id": user_id
            }
        ))
    except Exception as exc:
        db.rollback()
        log.error("save_message_and_increment failed: %s", exc)
        raise


def save_lead_atomic(
    db: Session,
    company_id: str,
    name: str,
    phone: Optional[str],
    interest: str,
    temperature: str = "cold",
    is_hot_deal: bool = False,
    needs_human_intervention: bool = False,
    lead_score: int = 0,
    status: str = "new",
    ai_summary: Optional[str] = None,
    last_message_preview: Optional[str] = None,
    conversation_state: str = "GREETING",
    whatsapp_number: str = None,
    whatsapp_jid: str = None,
    customer_provided_phone: str = None,
    channel_type: str = "WHATSAPP_QR",
    external_customer_id: str = None,
) -> bool:
    """
    True dialect-native UPSERT using INSERT … ON CONFLICT DO UPDATE.
    Never blocks on a concurrent insert — the DB resolves the conflict atomically.
    Returns True if a new row was created, False if an existing row was updated.
    """
    try:
        import json
        import re

        clean_phone = re.sub(r"\D", "", phone) if phone else None
        normalized_phone = (
            clean_phone[2:]
            if clean_phone and clean_phone.startswith("201") and len(clean_phone) >= 12
            else (clean_phone[1:] if clean_phone and clean_phone.startswith("01") and len(clean_phone) >= 11 else clean_phone)
        ) if clean_phone else None
        wa_num = whatsapp_number or normalized_phone

        # Check existence first strictly for event logging purposes (the actual DB write is atomic)
        if channel_type == "VELOR_WEB_CHAT":
            existing_lead = db.query(Lead.id).filter(
                Lead.company_id == company_id,
                Lead.channel_type == "VELOR_WEB_CHAT",
                Lead.external_customer_id == external_customer_id
            ).first()
        else:
            existing_lead = db.query(Lead.id).filter(Lead.company_id == company_id, Lead.whatsapp_number == wa_num).first()
        is_new = existing_lead is None

        stmt = _dialect_insert(Lead).values(
            uuid=str(uuid.uuid4()),
            company_id=company_id,
            name=name,
            phone=normalized_phone,
            whatsapp_number=wa_num,
            whatsapp_jid=whatsapp_jid,
            customer_provided_phone=customer_provided_phone,
            interest=interest,
            temperature=temperature,
            is_hot_deal=is_hot_deal,
            needs_human_intervention=needs_human_intervention,
            lead_score=lead_score,
            status=status,
            ai_summary=ai_summary,
            last_message_preview=last_message_preview,
            conversation_state=conversation_state,
            is_deleted=False,
            deleted_at=None,
            channel_type=channel_type,
            external_customer_id=external_customer_id,
        )

        update_dict = {
            "name": name,
            "phone": normalized_phone,
            "customer_provided_phone": customer_provided_phone,
            "interest": interest,
            "temperature": temperature,
            "is_hot_deal": is_hot_deal,
            "needs_human_intervention": needs_human_intervention,
            "lead_score": lead_score,
            "status": status,
            "ai_summary": ai_summary,
            "last_message_preview": last_message_preview,
            "conversation_state": conversation_state,
            "is_deleted": False,
            "deleted_at": None,
            "updated_at": func.now(),
        }

        # True atomic UPSERT
        if channel_type == "VELOR_WEB_CHAT":
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["company_id", "channel_type", "external_customer_id"],
                set_=update_dict
            )
        else:
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["company_id", "whatsapp_number"],
                set_=update_dict
            )

        db.execute(upsert_stmt)

        if is_new:
            _upsert_usage_in_session(db, company_id, leads=1)

        event_payload = json.dumps({"phone": normalized_phone, "name": name, "status": status, "is_new": is_new})
        db.add(
            SystemEvent(
                company_id=company_id, event_type="lead.created" if is_new else "lead.updated", entity_id=normalized_phone or external_customer_id, payload=event_payload
            )
        )

        db.commit()
        
        from engine.intelligence_bus import bus, IntelligenceEvent, EventSeverity
        bus.publish_sync(IntelligenceEvent(
            topic="lead.created" if is_new else "lead.updated",
            severity=EventSeverity.INFO,
            company_id=company_id,
            payload={"phone": normalized_phone, "name": name, "status": status, "is_new": is_new}
        ))
        
        return is_new

    except Exception as exc:
        db.rollback()
        log.error("save_lead_atomic error: %s", exc)
        return False


# ─────────────────────────────────────────────────
# PERSISTENCE API
# ─────────────────────────────────────────────────


def _upsert_usage_in_session(
    db: Session,
    company_id: str,
    messages: int = 0,
    leads: int = 0,
    requests: int = 0,
) -> None:
    """Mutate UsageStats without committing inside the caller's transaction."""
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    row = db.query(UsageStats).filter(UsageStats.company_id == company_id).first()

    if row:
        # Reset monthly counters if we crossed a month boundary
        if row.current_month != current_month:
            row.current_month = current_month
            row.monthly_messages = 0
            row.monthly_leads = 0

        row.messages_count += messages
        row.leads_count += leads
        row.requests_count += requests
        row.monthly_messages += messages
        row.monthly_leads += leads
    else:
        db.add(
            UsageStats(
                company_id=company_id,
                messages_count=messages,
                leads_count=leads,
                requests_count=requests,
                current_month=current_month,
                monthly_messages=messages,
                monthly_leads=leads,
            )
        )


def save_message(
    db: Session,
    company_id: str,
    user_id: str,
    sender: str,
    message: str,
    internal_message_id: str,
    direction: str,
    wa_message_id: str = None,
    delivery_status: str = "pending",
) -> None:
    save_message_and_increment_atomic(db, company_id, user_id, sender, message, internal_message_id, direction, wa_message_id, delivery_status)


def save_lead(
    db: Session,
    company_id: str,
    name: str,
    phone: str,
    interest: str,
    temperature: str = "cold",
    is_hot_deal: bool = False,
    needs_human_intervention: bool = False,
    lead_score: int = 0,
    status: str = "new",
    ai_summary: Optional[str] = None,
    last_message_preview: Optional[str] = None,
    conversation_state: str = "GREETING",
    whatsapp_number: str = None,
    whatsapp_jid: str = None,
    customer_provided_phone: str = None,
) -> bool:
    return save_lead_atomic(
        db,
        company_id,
        name,
        phone,
        interest,
        temperature,
        is_hot_deal,
        needs_human_intervention,
        lead_score,
        status,
        ai_summary,
        last_message_preview,
        conversation_state,
        whatsapp_number,
        whatsapp_jid,
        customer_provided_phone,
    )


def get_latest_leads(db: Session, company_id: str, limit: int = 10) -> List[Dict[str, str]]:
    rows = (
        db.query(Lead)
        .options(joinedload(Lead.intelligence_snapshot))
        .filter(Lead.company_id == company_id, Lead.is_deleted == False, Lead.is_test == False)
        .order_by(Lead.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "name": r.name,
            "phone": r.whatsapp_number or r.phone,
            "customer_provided_phone": r.customer_provided_phone,
            "interest": r.interest,
            "is_paused": r.is_paused,
            "temperature": r.temperature,
            "is_hot_deal": r.is_hot_deal,
            "needs_human_intervention": r.needs_human_intervention,
            "lead_score": r.lead_score,
            "status": r.status,
            "ai_summary": r.ai_summary,
            "last_message_preview": r.last_message_preview,
            "last_message": r.last_message,
            "conversation_count": r.conversation_count,
            "first_contact_date": r.first_contact_date.isoformat() if r.first_contact_date else None,
            "last_contact_date": r.last_contact_date.isoformat() if r.last_contact_date else None,
            "_ts": r.created_at.strftime("%I:%M %p") if r.created_at else "",
            "stage": r.stage,
            "conversation_state": r.conversation_state,
            "intelligence_snapshot": (
                {
                    "intent_score": r.intent_score,
                    "priority_score": getattr(r.intelligence_snapshot, "priority_score", None),
                    "lost_risk_score": getattr(r.intelligence_snapshot, "lost_risk_score", None),
                    "next_best_action": getattr(r.intelligence_snapshot, "next_best_action", None),
                    "action_reason": getattr(r.intelligence_snapshot, "action_reason", None),
                    "why_summary": getattr(r.intelligence_snapshot, "why_summary", None),
                }
                if getattr(r, "intelligence_snapshot", None)
                else None
            ),
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────
# 🏢 COMPANY HELPERS
# ─────────────────────────────────────────────────


def create_company(
    db: Session,
    company_id: str,
    company_name: str,
    email: str,
    password: str,
    api_key: str,
    role: str = "tenant",
    plan: str = "FREE",
    auth_provider: str = "password",
    google_subject: Optional[str] = None,
    terms_accepted_at: Optional[datetime] = None,
    terms_version: Optional[str] = None,
    privacy_version: Optional[str] = None,
) -> None:
    db.add(
        Company(
            company_id=company_id,
            company_name=company_name,
            email=email.lower().strip(),
            password=get_password_hash(password),
            api_key_hash=hash_api_key(api_key),
            role=role,
            plan=plan,
            auth_provider=auth_provider,
            google_subject=google_subject,
            terms_accepted_at=terms_accepted_at,
            terms_version=terms_version,
            privacy_version=privacy_version,
        )
    )
    db.add(UsageStats(company_id=company_id))
    db.commit()
    log.info("Company created: %s [%s/%s]", company_name, role, plan)


def toggle_lead_pause(db: Session, company_id: str, phone: str) -> bool:
    base_phone = normalize_whatsapp_number(phone)
    lead = (
        db.query(Lead)
        .filter(Lead.company_id == company_id, (Lead.whatsapp_number == base_phone) | (Lead.phone.in_(get_phone_variants(base_phone))))
        .first()
    )
    if lead:
        lead.is_paused = not lead.is_paused
        db.commit()
        return lead.is_paused
    return False


def is_lead_paused(db: Session, company_id: str, phone: str) -> bool:
    base_phone = normalize_whatsapp_number(phone)
    lead = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            (Lead.whatsapp_number == base_phone) | 
            (Lead.phone.in_(get_phone_variants(base_phone))) |
            (Lead.external_customer_id == phone)
        )
        .first()
    )
    return lead.is_paused if lead else False



def get_company_knowledge(db: Session, company_id: str) -> Dict[str, str]:
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id, CompanyKnowledge.is_deleted == False).first()
    c = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    company_name = c.company_name if c else ''

    if k:
        return {
            'company_name': company_name,
            'industry': k.industry or '',
            'system_prompt': k.system_prompt,
            'products_data': k.products_data,
            'google_sheet_webhook_url': k.google_sheet_webhook_url,
            'welcome_message': k.welcome_message,
            'suggested_questions': k.suggested_questions,
            'knowledge_base': k.knowledge_base,
            'language': k.language,
            'tone': k.tone,
            'lead_collection': k.lead_collection,
        }
    return {
        'company_name': company_name,
        'industry': '',
        'system_prompt': 'أنت مساعد مبيعات محترف.',
        'products_data': '',
        'google_sheet_webhook_url': None,
        'welcome_message': '',
        'suggested_questions': '',
        'knowledge_base': '',
        'language': 'Arabic',
        'tone': 'Professional',
        'lead_collection': True,
    }

def update_company_knowledge(
    db: Session,
    company_id: str,
    system_prompt: Optional[str] = None,
    products_data: Optional[str] = None,
    google_sheet_webhook_url: Optional[str] = None,
    welcome_message: str = '',
    suggested_questions: str = '',
    knowledge_base: Optional[str] = None,
    language: str = 'Arabic',
    tone: str = 'Professional',
    lead_collection: bool = True,
    company_name: str = '',
    industry: str = '',
) -> None:
    if company_name:
        c = db.query(Company).filter(Company.company_id == company_id).first()
        if c:
            c.company_name = company_name

    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    if k:
        if system_prompt is not None:
            k.system_prompt = system_prompt
        if products_data is not None:
            k.products_data = products_data
        k.google_sheet_webhook_url = google_sheet_webhook_url
        k.welcome_message = welcome_message
        k.suggested_questions = suggested_questions
        if knowledge_base is not None:
            k.knowledge_base = knowledge_base
        k.language = language
        k.tone = tone
        k.lead_collection = lead_collection
        k.industry = industry
    else:
        db.add(
            CompanyKnowledge(
                company_id=company_id,
                system_prompt=system_prompt if system_prompt is not None else "أنت مساعد مبيعات محترف.",
                products_data=products_data if products_data is not None else '[]',
                google_sheet_webhook_url=google_sheet_webhook_url,
                welcome_message=welcome_message,
                suggested_questions=suggested_questions,
                knowledge_base=knowledge_base or '',
                language=language,
                tone=tone,
                lead_collection=lead_collection,
                industry=industry,
            )
        )
    db.commit()


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(64), ForeignKey("companies.company_id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    read_at = Column(DateTime, nullable=True)
    uuid = Column(String(36), default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)


def get_monthly_usage(db: Session, company_id: str) -> Tuple[int, int]:
    """Returns (monthly_messages, monthly_leads) for the current month."""
    row = db.query(UsageStats).filter(UsageStats.company_id == company_id).first()
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if row and row.current_month == current_month:
        return row.monthly_messages, row.monthly_leads
    return (0, 0)


def get_user_history(
    db: Session,
    company_id: str,
    user_id: str,
    limit: int = 6,
    before_message_id: Optional[int] = None,
) -> List[Dict[str, str]]:
    base_phone = normalize_whatsapp_number(user_id)
    query = db.query(Message).filter(
        Message.company_id == company_id,
        Message.is_deleted == False,
        (Message.user_id == base_phone) | (Message.user_id.in_(get_phone_variants(base_phone))),
    )
    if before_message_id is not None:
        query = query.filter(Message.id < int(before_message_id))
    messages = (
        query
        # SQLite timestamps are often second-granular.  The message id breaks
        # ties so conversational context always follows the actual turn order.
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    return [{"sender": m.sender, "message": m.message} for m in messages]



def create_refresh_token(db: Session, company_id: str, expire_days: int = 30) -> str:
    raw = generate_refresh_token()
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
    db.add(RefreshToken(company_id=company_id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return raw


def rotate_refresh_token(db: Session, raw_token: str) -> Optional[Tuple[str, Company]]:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .first()
    )
    if not row or row.revoked:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at and row.expires_at.replace(tzinfo=timezone.utc) < now:
        return None

    row.revoked = True
    company_id = row.company_id
    comp = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not comp:
        return None

    new_raw = generate_refresh_token()
    new_hash = hashlib.sha256(new_raw.encode()).hexdigest()
    db.add(
        RefreshToken(
            company_id=company_id,
            token_hash=new_hash,
            expires_at=now + timedelta(days=30),
        )
    )
    db.commit()
    return new_raw, comp


def revoke_refresh_token(db: Session, raw_token: str, company_id: Optional[str] = None) -> bool:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    query = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash)
    if company_id:
        query = query.filter(RefreshToken.company_id == company_id)
    row = query.first()
    if row:
        row.revoked = True
        db.commit()
        return True
    return False


def cleanup_expired_tokens(db: Session) -> int:
    try:
        now = datetime.now(timezone.utc)
        result = db.query(RefreshToken).filter((RefreshToken.expires_at <= now) | (RefreshToken.revoked == True)).delete(synchronize_session=False)
        db.commit()
        log.info("Cleaned up %d expired/revoked refresh tokens", result)
        return result
    except Exception as exc:
        db.rollback()
        log.error("cleanup_expired_tokens error: %s", exc)
        return 0


def cleanup_old_audit_logs(db: Session, retention_days: int = 90) -> int:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        result = db.query(AuditLog).filter(AuditLog.created_at <= cutoff).delete(synchronize_session=False)
        db.commit()
        log.info("Cleaned up %d audit logs older than %d days", result, retention_days)
        return result
    except Exception as exc:
        db.rollback()
        log.error("cleanup_old_audit_logs error: %s", exc)
        return 0


def write_audit_log(
    db: Session,
    event_type: str,
    company_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    try:
        db.add(AuditLog(company_id=company_id, event_type=event_type, ip_address=ip_address, user_agent=user_agent, detail=detail))
        db.commit()
    except Exception as exc:
        db.rollback()
        log.error("write_audit_log error: %s", exc)


def get_leads_paginated(
    db: Session,
    company_id: str,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    q = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == False,
    )
    total = q.count()
    items = q.order_by(Lead.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    pages = (total + page_size - 1) // page_size if total > 0 else 1
    return {"total": total, "page": page, "page_size": page_size, "pages": pages, "items": items}


def get_conversations_paginated(
    db: Session,
    company_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    base_phone = normalize_whatsapp_number(user_id)
    q = db.query(Message).filter(
        Message.company_id == company_id,
        Message.is_deleted == False,
        (Message.user_id == base_phone) | (Message.user_id.in_(get_phone_variants(base_phone))),
    )
    total = q.count()
    items = q.order_by(Message.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    pages = (total + page_size - 1) // page_size if total > 0 else 1
    return {"total": total, "page": page, "page_size": page_size, "pages": pages, "items": items}


def fail_pending_messages(db: Session, minutes_old: int = 5) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    messages = (
        db.query(Message)
        .filter(
            Message.delivery_status == "pending",
            Message.created_at <= cutoff,
        )
        .limit(500)
        .all()
    )
    count = 0
    for msg in messages:
        msg.delivery_status = "failed"
        db.add(MessageEvent(message_id=msg.id, status="failed"))
        count += 1
    if count:
        db.commit()
    return count


def get_active_leads_query(db: Session, company_id: str):
    return db.query(Lead).filter(Lead.company_id == company_id, Lead.is_deleted == False, get_live_leads_filter(Lead))


def get_open_leads_query(db: Session, company_id: str):
    return get_active_leads_query(db, company_id).filter(Lead.stage.notin_(["Won", "Lost"]))


def get_terminal_leads_query(db: Session, company_id: str):
    return get_active_leads_query(db, company_id).filter(Lead.stage.in_(["Won", "Lost"]))


def get_won_leads_query(db: Session, company_id: str):
    return get_active_leads_query(db, company_id).filter(Lead.stage == "Won")


def get_lost_leads_query(db: Session, company_id: str):
    return get_active_leads_query(db, company_id).filter(Lead.stage == "Lost")


def get_priority_leads_query(db: Session, company_id: str):
    return (
        db.query(LeadIntelligenceSnapshot, Lead)
        .join(Lead, LeadIntelligenceSnapshot.lead_id == Lead.id)
        .filter(
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            get_live_leads_filter(Lead),
            Lead.stage.notin_(["Won", "Lost"]),
            LeadIntelligenceSnapshot.priority_score > 0,
        )
    )


def get_hot_leads_query(db: Session, company_id: str):
    return get_open_leads_query(db, company_id).filter(
        (Lead.is_hot_deal == True) | (Lead.status.in_(["شراء مؤكد", "اهتمام عالي", "qualified", "فرصة واعدة"]))
    )


def get_at_risk_leads_query(db: Session, company_id: str):
    return (
        db.query(Lead)
        .outerjoin(LeadIntelligenceSnapshot, Lead.id == LeadIntelligenceSnapshot.lead_id)
        .filter(
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            get_live_leads_filter(Lead),
            Lead.stage.notin_(["Won", "Lost"]),
            (Lead.needs_human_intervention == True)
            | (Lead.status.in_(["محتاج تدخل / غاضب 🚨", "angry"]))
            | (LeadIntelligenceSnapshot.lost_risk_score >= 70),
        )
    )


def get_urgent_intervention_query(db: Session, company_id: str):
    return get_open_leads_query(db, company_id).filter(
        (Lead.needs_human_intervention == True)
        | (Lead.is_hot_deal == True)
        | (Lead.status.in_(["محتاج تدخل / غاضب 🚨", "angry", "شراء مؤكد", "اهتمام عالي"]))
    )
