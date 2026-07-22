"""
main.py — VELOR FastAPI Application  v3
==========================================
Issues fixed:
  #2  Refresh Token Rotation — /token/refresh now revokes old + issues new
  #3  Scheduler started on app startup (token cleanup daily)
  #4  Scheduler started on app startup (audit log retention daily)
  #6  Plan enforcement — check monthly quota before every /chat call
  #7  ENV=production disables Swagger/ReDoc
  #11 Same as #7 (ENV-based docs toggle)
"""

import csv
import io
import logging
import os
import re
import secrets
import asyncio
import anyio
from threading import BoundedSemaphore
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from enum import Enum
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from database import (
    get_phone_variants,
    normalize_whatsapp_number,
    AuditLog,
    Company,
    Message,
    Lead,
    Notification,
    FollowUpTask,
    LeadMemory,
    LeadEvent,
    LeadSignal,
    MessageEvent,
    SystemEvent,
    SessionLocal,
    create_company,
    create_refresh_token,
    generate_api_key,
    get_conversations_paginated,
    get_db,
    get_leads_paginated,
    get_monthly_usage,
    hash_api_key,
    revoke_refresh_token,
    rotate_refresh_token,
    timing_safe_verify,
    write_audit_log,
    save_message,
    get_live_leads_filter,
    get_priority_leads_query,
    get_latest_leads,
    toggle_lead_pause,
    is_lead_paused,
)
from services.context_engine import summarize_conversation
from services.message_delivery import apply_message_delivery_update
from brain import get_ai_response, generate_advanced_system_prompt, latest_quick_replies, groq_client
from plan_config import get_limits, check_lead_quota, check_message_quota
from prompt_limits import COMPANY_SYSTEM_PROMPT_MAX_CHARS, validate_company_system_prompt
from scheduler import start_scheduler, stop_scheduler



# ─────────────────────────────────────────────────
# ⚙️ CONFIG
# ─────────────────────────────────────────────────
load_dotenv()
log = logging.getLogger("adam.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

JWT_SECRET: str = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60
ENV: str = os.getenv("ENV", "development")
NODE_INTERNAL_SECRET: str = os.getenv("NODE_INTERNAL_SECRET", "")
NODE_GATEWAY_URL: str = os.getenv("NODE_GATEWAY_URL", "http://127.0.0.1:3005")
TERMS_VERSION: str = os.getenv("TERMS_VERSION", "2026-07-15")
PRIVACY_VERSION: str = os.getenv("PRIVACY_VERSION", "2026-07-15")


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    """Serialize persisted timestamps as explicit UTC, including SQLite rows.

    SQLite drops timezone information even for ``timezone=True`` columns. The
    old API emitted those values without an offset, so browsers interpreted
    UTC rows as Cairo wall time and inflated/deflated elapsed durations.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_public_web_chat_engine() -> str:
    """Resolve the one public-chat engine control.

    V2 is the safe default.  ``PUBLIC_WEB_CHAT_RESPONSE_ENGINE=v1`` is the
    explicit, temporary rollback.  The legacy V2 flag is accepted only for
    backwards-compatible deployments and cannot silently force V1.
    """
    configured = os.getenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "").strip().casefold()
    if configured == "v1":
        return "v1"
    if configured == "v2":
        return "v2"
    return "v2"


def validate_runtime_configuration() -> None:
    configured_engine = os.getenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "").strip().casefold()
    if configured_engine and configured_engine not in {"v1", "v2"}:
        raise ValueError("PUBLIC_WEB_CHAT_RESPONSE_ENGINE must be v1 or v2")
    configured_whatsapp_engine = os.getenv("WHATSAPP_RESPONSE_ENGINE", "").strip().casefold()
    if configured_whatsapp_engine and configured_whatsapp_engine not in {"v1", "v2"}:
        raise ValueError("WHATSAPP_RESPONSE_ENGINE must be v1 or v2")
    configured_external_engine = os.getenv("EXTERNAL_API_RESPONSE_ENGINE", "").strip().casefold()
    if configured_external_engine and configured_external_engine not in {"v1", "v2"}:
        raise ValueError("EXTERNAL_API_RESPONSE_ENGINE must be v1 or v2")
    numeric_settings = (
        "PUBLIC_CHAT_REPLY_TIMEOUT_SECONDS",
        "WHATSAPP_REPLY_TIMEOUT_SECONDS",
        "VELOR_PROVIDER_TIMEOUT_SECONDS",
        "VELOR_WRITER_MAX_TOKENS",
        "WEBHOOK_INBOX_STALE_SECONDS",
        "WEBHOOK_INBOX_MAX_ATTEMPTS",
        "PUBLIC_CHAT_SESSION_IP_LIMIT_PER_MINUTE",
        "PUBLIC_CHAT_SESSION_TENANT_LIMIT_PER_MINUTE",
        "PUBLIC_CHAT_IP_LIMIT_PER_MINUTE",
        "PUBLIC_CHAT_VISITOR_LIMIT_PER_MINUTE",
        "PUBLIC_CHAT_TENANT_LIMIT_PER_MINUTE",
        "GLOBAL_RATE_LIMIT_PER_MINUTE",
        "KNOWLEDGE_UPLOAD_MAX_BYTES",
        "KNOWLEDGE_EXTRACTED_MAX_CHARS",
        "KNOWLEDGE_COMPILED_MAX_CHARS",
    )
    for name in numeric_settings:
        value = os.getenv(name)
        if value in {None, ""}:
            continue
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if parsed <= 0:
            raise ValueError(f"{name} must be greater than zero")

    writer_temperature = os.getenv("VELOR_WRITER_TEMPERATURE")
    if writer_temperature not in {None, ""}:
        try:
            parsed_temperature = float(writer_temperature)
        except ValueError as exc:
            raise ValueError("VELOR_WRITER_TEMPERATURE must be numeric") from exc
        if not 0 <= parsed_temperature <= 0.7:
            raise ValueError("VELOR_WRITER_TEMPERATURE must be between 0 and 0.7")

    if ENV in {"verification", "staging", "production"}:
        from services.conversation_engine_config import (
            get_external_api_response_engine,
            get_whatsapp_response_engine,
        )

        if get_public_web_chat_engine() != "v2":
            raise ValueError("Release environments require PUBLIC_WEB_CHAT_RESPONSE_ENGINE=v2")
        if get_whatsapp_response_engine() != "v2":
            raise ValueError("Release environments require WHATSAPP_RESPONSE_ENGINE=v2")
        if get_external_api_response_engine() != "v2":
            raise ValueError("Release environments require EXTERNAL_API_RESPONSE_ENGINE=v2")
        database_url = os.getenv("DATABASE_URL", "").strip().casefold()
        if database_url.startswith("sqlite"):
            raise ValueError("Release environments require PostgreSQL; SQLite is not supported")
        allowed_hosts = [
            host.strip()
            for host in os.getenv("ALLOWED_HOSTS", "").split(",")
            if host.strip()
        ]
        if not allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must be an explicit allowlist in release environments")
        if "*" in allowed_hosts:
            raise ValueError("Release ALLOWED_HOSTS cannot contain a wildcard")

    meta_enabled = os.getenv("ENABLE_META_WEBHOOK", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if meta_enabled:
        required_meta = (
            "VELOR_META_VERIFY_TOKEN",
            "META_APP_SECRET",
            "META_GRAPH_API_TOKEN",
            "META_PHONE_NUMBER_ID",
        )
        missing_meta = [name for name in required_meta if not os.getenv(name, "").strip()]
        if missing_meta:
            raise ValueError(
                "Meta webhook enabled but required settings are missing: "
                + ", ".join(missing_meta)
            )
        if not (
            os.getenv("META_COMPANY_ID", "").strip()
            or os.getenv("META_PHONE_COMPANY_MAP", "").strip()
        ):
            raise ValueError(
                "Meta webhook enabled but no company mapping is configured"
            )

FORBIDDEN_PRODUCTION_SECRETS = {
    "super-secret-test-key-32-chars-long",
    "default-secret",
    "super-secret",
    "secret",
    "12345678901234567890123456789012"
}

if not JWT_SECRET or len(JWT_SECRET) < 32:
    raise ValueError("JWT_SECRET missing or too short (min 32 chars)!")

if ENV == "production":
    if JWT_SECRET in FORBIDDEN_PRODUCTION_SECRETS or "test" in JWT_SECRET.lower() or "default" in JWT_SECRET.lower():
        raise ValueError("JWT_SECRET cannot be a default, weak, or test key in production!")

if ENV in {"verification", "staging", "production"}:
    if len(NODE_INTERNAL_SECRET) < 32:
        raise ValueError("NODE_INTERNAL_SECRET missing or too short for a release environment (min 32 chars)!")
    lowered_node_secret = NODE_INTERNAL_SECRET.casefold()
    if any(marker in lowered_node_secret for marker in ("test", "default", "replace", "example")):
        raise ValueError("NODE_INTERNAL_SECRET cannot be a placeholder or test value in a release environment")
    if secrets.compare_digest(NODE_INTERNAL_SECRET, JWT_SECRET):
        raise ValueError("NODE_INTERNAL_SECRET and JWT_SECRET must be different")

# Tunable limit to bound the number of concurrent DB worker threads
# Should be set to a value <= your DB pool size to avoid exhausting connections
_DB_WORKER_LIMIT = int(os.getenv("VELOR_DB_WORKER_LIMIT", os.getenv("ADAM_DB_WORKER_LIMIT", "20")))
_DB_WORKER_SEM = BoundedSemaphore(_DB_WORKER_LIMIT)

# #11 — Swagger only in non-production
_docs_url = "/docs" if ENV != "production" else None
_redoc_url = "/redoc" if ENV != "production" else None


# ─────────────────────────────────────────────────
# 🔄 LIFESPAN  (Issues #3, #4 — start scheduler)
# ─────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import assert_database_schema_compatible, get_database_runtime_summary

    validate_runtime_configuration()
    strict_startup = ENV in {"verification", "staging", "production"}
    if strict_startup:
        # Release environments fail closed before accepting traffic.  Provider
        # availability is intentionally not part of this fatal gate because the
        # bounded V2 fallback is a supported degraded mode.
        assert_database_schema_compatible(require_migration_head=True)
    else:
        summary = get_database_runtime_summary(require_migration_head=False)
        if not summary.get("schema_compatible"):
            log.warning("Database schema is not ready for normal traffic [ENV=%s]", ENV)

    start_scheduler()  # starts cleanup cron jobs
    log.info("🚀 VELOR started [ENV=%s]", ENV)
    try:
        yield
    finally:
        stop_scheduler()
        log.info("🛑 VELOR stopped")


app = FastAPI(
    title="VELOR API",
    version="3.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)





# ── Rate limiter ──
from slowapi.middleware import SlowAPIMiddleware
import redis

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
storage_uri = "memory://"
try:
    r = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    r.ping()
    storage_uri = redis_url
    log.info("RateLimiter connected to Redis")
except Exception as e:
    if ENV in {"verification", "staging", "production"}:
        raise RuntimeError("Redis is required for distributed rate limiting in release environments") from e
    log.warning("Redis unavailable, RateLimiter falling back to memory: %s", e)

_global_rate_limit = int(os.getenv("GLOBAL_RATE_LIMIT_PER_MINUTE", "100"))
limiter = Limiter(key_func=get_remote_address, storage_uri=storage_uri, default_limits=[f"{_global_rate_limit}/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

from routers import crm, intelligence, knowledge, stream, webhook, operations, catalog
from copilot import router as copilot_router

app.include_router(crm.router)
app.include_router(intelligence.router)
app.include_router(knowledge.router)
app.include_router(stream.router)
app.include_router(webhook.router)
app.include_router(operations.router)
app.include_router(catalog.router)
app.include_router(copilot_router.router)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"success": False, "message": "لقد تجاوزت الحد المسموح من الطلبات، يرجى الانتظار."},
    )


# Phase 4: Unified error response format
@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "حدث خطأ داخلي في السيرفر، يرجى المحاولة لاحقاً.",
            "status_code": 500,
        },
    )


# ── CORS ──
_DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173,"
    "http://127.0.0.1:5173,"
    # Vite selects the next port when 5173 is already occupied. Keep the
    # local development fallback usable for an authenticated browser session.
    "http://localhost:5174,"
    "http://127.0.0.1:5174,"
    "http://localhost:4173,"
    "http://127.0.0.1:4173,"
    "http://localhost:3000,"
    "http://127.0.0.1:3000"
)
_configured_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
if ENV in {"verification", "staging", "production"} and not _configured_origins:
    raise ValueError("ALLOWED_ORIGINS must be an explicit HTTPS allowlist in release environments")
_raw_origins = _configured_origins or _DEFAULT_ALLOWED_ORIGINS
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
if ENV in {"verification", "staging", "production"}:
    if "*" in ALLOWED_ORIGINS or any(not origin.startswith("https://") for origin in ALLOWED_ORIGINS):
        raise ValueError("Release ALLOWED_ORIGINS must contain only explicit HTTPS origins")
if ENV in {"development", "test"}:
    for origin in _DEFAULT_ALLOWED_ORIGINS.split(","):
        if origin not in ALLOWED_ORIGINS:
            ALLOWED_ORIGINS.append(origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1,testserver"
_raw_allowed_hosts = os.getenv("ALLOWED_HOSTS", "").strip() or _DEFAULT_ALLOWED_HOSTS
ALLOWED_HOSTS = [host.strip() for host in _raw_allowed_hosts.split(",") if host.strip()]
if ENV in {"development", "test"}:
    for host in _DEFAULT_ALLOWED_HOSTS.split(","):
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def enforce_cookie_origin_and_security_headers(request: Request, call_next):
    """Protect cookie-authenticated mutations and attach API security headers."""
    has_merchant_cookie = bool(
        request.cookies.get("access_token") or request.cookies.get("refresh_token")
    )
    if has_merchant_cookie and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "Cross-site request blocked", "status_code": 403},
            )
        if ENV in {"verification", "staging", "production"} and not origin:
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "Origin header required", "status_code": 403},
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if ENV in {"verification", "staging", "production"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

bearer_scheme = HTTPBearer()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
internal_secret_header = APIKeyHeader(name="X-Internal-Secret", auto_error=False)
company_id_header = APIKeyHeader(name="X-Company-ID", auto_error=False)


# ─────────────────────────────────────────────────
# 📥 SCHEMAS
# ─────────────────────────────────────────────────
class ToneEnum(str, Enum):
    formal = "formal"
    casual = "casual"
    persuasive = "persuasive"
    friendly = "friendly"
    aggressive = "aggressive"
    custom = "custom"


class LanguageEnum(str, Enum):
    arabic_egyptian = "Arabic (Egyptian)"
    arabic_msa = "Arabic (MSA)"
    english = "English"
    french = "French"
    custom = "custom"


class WizardData(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=100)
    business_type: str = Field(..., min_length=2, max_length=100)
    business_description: str = Field("", max_length=2000)
    products_services: str = Field(..., min_length=5, max_length=1000)
    pricing_information: str = Field("", max_length=2000)
    contact_information: str = Field("", max_length=500)
    agent_name: str = Field("", max_length=100)
    bot_role: str = Field(..., min_length=5, max_length=200)
    tone: ToneEnum
    custom_tone: Optional[str] = Field(None, max_length=100)
    language: LanguageEnum
    custom_language: Optional[str] = Field(None, max_length=100)
    response_style: str = Field("Medium", max_length=50)
    collect_leads: bool = True
    collect_fields: str = Field("Name, Phone", max_length=200)

    @model_validator(mode="after")
    def check_custom_fields(self):
        if self.tone == ToneEnum.custom and not self.custom_tone:
            raise ValueError("custom_tone is required when tone is 'custom'")
        if self.language == LanguageEnum.custom and not self.custom_language:
            raise ValueError("custom_language is required when language is 'custom'")
        return self


class SignupData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    terms_accepted: bool

    @field_validator("company_name")
    @classmethod
    def _sanitize_name(cls, v: str) -> str:
        if re.search(r'[<>"\'\\;=]', v):
            raise ValueError("اسم الشركة يحتوي على رموز غير مسموح بها")
        return v.strip()

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("كلمة المرور طويلة أكثر من الحد الآمن")
        if not any(character.isalpha() for character in value) or not any(
            character.isdigit() for character in value
        ):
            raise ValueError("استخدم حرفًا ورقمًا واحدًا على الأقل في كلمة المرور")
        return value

    @field_validator("terms_accepted")
    @classmethod
    def _require_legal_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Terms and privacy consent is required")
        return value


class LoginData(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class GoogleAuthData(BaseModel):
    token: str
    terms_accepted: bool = False


class KnowledgeData(BaseModel):
    system_prompt: str = Field(..., min_length=10, max_length=3000)
    products_data: str = Field(..., max_length=5000)
    google_sheet_webhook_url: Optional[str] = Field(None, max_length=500)
    welcome_message: Optional[str] = Field("", max_length=1000)
    suggested_questions: Optional[str] = Field("", max_length=1000)
    knowledge_base: Optional[str] = Field("", max_length=10000)
    industry: Optional[str] = Field("", max_length=200)
    company_name: Optional[str] = Field("", max_length=200)
    language: Optional[str] = Field("Arabic", max_length=100)
    tone: Optional[str] = Field("Professional", max_length=100)
    lead_collection: bool = True


class TakeoverRequest(BaseModel):
    phone: str
    message: str
    # Optional compare-and-set boundary used only when the text came from a
    # VELOR draft. Plain owner-authored messages remain backward compatible.
    source_message_internal_id: Optional[str] = Field(None, min_length=1, max_length=64)
    suggestion_id: Optional[int] = Field(None, ge=1)
    variant_style: Optional[str] = Field(None, min_length=1, max_length=40)
    suggestion_edited: Optional[bool] = None


class AlertSettingsData(BaseModel):
    is_alerts_enabled: bool = False
    alert_whatsapp_number: Optional[str] = Field(None, max_length=20)

    @field_validator("alert_whatsapp_number")
    @classmethod
    def _validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v:
            if not re.match(r"^\+?[\d\s\-]+$", v):
                raise ValueError("رقم واتساب غير صالح")
        return v


class ChatMsg(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    user_id: str = Field(..., min_length=1, max_length=100)
    external_message_id: Optional[str] = Field(None, max_length=128)

    @field_validator("user_id")
    @classmethod
    def _sanitize_user_id(cls, v: str) -> str:
        if not re.match(r"^[\w\-@:.+]+$", v):
            raise ValueError("user_id يحتوي على رموز غير مسموح بها")
        return v

    @field_validator("external_message_id")
    @classmethod
    def _sanitize_external_message_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not re.match(r"^[\w\-:.]+$", v):
            raise ValueError("external_message_id contains invalid characters")
        return v


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class AckPayload(BaseModel):
    company_id: Optional[str] = None
    internal_message_id: Optional[str] = None
    wa_message_id: Optional[str] = None
    status: str
    timestamp: Optional[datetime] = None


class LeadStatusUpdate(BaseModel):
    status: str


class CompanyTargetUpdate(BaseModel):
    target: int = Field(..., ge=1, le=10000)


class AISuggestionRequest(BaseModel):
    client_name: str
    is_first_takeover: bool
    chat_history: list[str]


class BotAutoReplyUpdate(BaseModel):
    enabled: bool


class HumanTakeoverUpdate(BaseModel):
    enabled: Optional[bool] = None


# ─────────────────────────────────────────────────
# 🔐 AUTH HELPERS
# ─────────────────────────────────────────────────
def _create_access_token(company_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": company_id,  # RFC 7519 subject
            "company_id": company_id,  # backward-compat claim
            "role": role,
            "token_type": "access",  # guards against using refresh tokens here
            "iat": now,  # issued-at
            "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
            "jti": str(uuid.uuid4()),  # unique ID (future blacklisting)
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _get_client_ip(request: Request) -> str:
    trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "false").strip().casefold() == "true"
    fwd = request.headers.get("X-Forwarded-For") if trust_proxy else None
    direct = request.client.host if request.client else "unknown"
    return (fwd.split(",")[0].strip() if fwd else direct) or "unknown"


def _verify_internal_secret(value: Optional[str]) -> bool:
    if not NODE_INTERNAL_SECRET or not value:
        return False
    return secrets.compare_digest(value, NODE_INTERNAL_SECRET)


def _node_headers() -> dict[str, str]:
    if not NODE_INTERNAL_SECRET:
        raise HTTPException(status_code=500, detail="NODE_INTERNAL_SECRET is not configured")
    return {"X-Internal-Secret": NODE_INTERNAL_SECRET}


def _cookie_security() -> dict:
    is_release = ENV in {"verification", "staging", "production"}
    return {
        "httponly": True,
        "secure": is_release,
        "samesite": "lax",
    }


def _get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    # نقرأ التوكن من الكوكيز بدلاً من الهيدر (لمنع الـ XSS)
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Token missing or expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("token_type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        cid: str = payload.get("company_id", "")
        if not cid:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        company = db.query(Company).filter(
            Company.company_id == cid,
            Company.is_deleted == False,
        ).first()
        if not company:
            raise HTTPException(status_code=401, detail="Account is unavailable")
        return {"company_id": company.company_id, "role": company.role}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalid or expired")


def _resolve_company_id(
    request: Request,
    current_user: dict = Depends(_get_current_user),
) -> str:
    if current_user["role"] == "super_admin":
        cid = request.query_params.get("company_id")
        if not cid:
            raise HTTPException(status_code=400, detail="company_id مطلوب للأدمن")
        if not re.match(r"^[\w\-]+$", cid):
            raise HTTPException(status_code=400, detail="company_id غير صالح")
        return cid
    query_cid = request.query_params.get("company_id")
    if query_cid and query_cid != current_user["company_id"]:
        raise HTTPException(status_code=403, detail="⚠️ غير مسموح بالوصول لبيانات شركات أخرى")
    return current_user["company_id"]


def _sanitize_csv(val: str) -> str:
    val = str(val or "").strip()
    if val.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{val}"
    return val


def _find_lead_for_user(db: Session, company_id: str, user_id: str) -> Optional[Lead]:
    base_phone = normalize_whatsapp_number(user_id)
    variants = set(get_phone_variants(base_phone))
    if base_phone:
        variants.add(base_phone)
    variants.add(str(user_id))

    return (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            (Lead.whatsapp_number.in_(variants)) | (Lead.phone.in_(variants)) | (Lead.whatsapp_jid == str(user_id)) | (Lead.external_customer_id == str(user_id)),
        )
        .first()
    )


def _auto_reply_skip_reason(db: Session, company: Company, user_id: str) -> Optional[str]:
    if getattr(company, "bot_auto_reply_enabled", True) is False:
        return "company_auto_reply_disabled"

    lead = _find_lead_for_user(db, company.company_id, user_id)
    if lead and lead.is_paused:
        return "human_takeover_active"

    return None


def _record_auto_reply_skip(db: Session, company_id: str, user_id: str, internal_message_id: str, reason: str) -> None:
    db.add(
        SystemEvent(
            company_id=company_id,
            event_type="auto_reply.skipped",
            entity_id=internal_message_id,
            payload=json.dumps(
                {
                    "user_id": user_id,
                    "internal_message_id": internal_message_id,
                    "reason": reason,
                    "auto_reply_skipped": True,
                    "timestamp": _iso_utc(datetime.now(timezone.utc)),
                }
            ),
        )
    )
    db.commit()


def _existing_auto_reply_skip_reason(db: Session, company_id: str, internal_message_id: str) -> Optional[str]:
    event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.company_id == company_id,
            SystemEvent.event_type == "auto_reply.skipped",
            SystemEvent.entity_id == internal_message_id,
        )
        .order_by(SystemEvent.created_at.desc())
        .first()
    )
    if not event:
        return None
    try:
        payload = json.loads(event.payload or "{}")
    except Exception:
        return "auto_reply_skipped"
    return payload.get("reason") or "auto_reply_skipped"


def _ensure_lead_for_skipped_auto_reply(db: Session, company_id: str, user_id: str, message: str) -> Optional[Lead]:
    lead = _find_lead_for_user(db, company_id, user_id)
    if not lead:
        if user_id.startswith("wc_v_"):
            lead = Lead(
                company_id=company_id,
                name="Potential Customer",
                phone=None,
                whatsapp_number=None,
                whatsapp_jid=None,
                channel_type="VELOR_WEB_CHAT",
                external_customer_id=user_id,
                interest="General",
                last_message=message,
                last_message_sender="user",
                last_message_preview=message[:500],
                conversation_count=1,
            )
        else:
            base_phone = normalize_whatsapp_number(user_id)
            fallback_phone = re.sub(r"\D", "", str(user_id))[:20]
            lead = Lead(
                company_id=company_id,
                name="Potential Customer",
                phone=(base_phone or fallback_phone or str(user_id)[:20]),
                whatsapp_number=(base_phone[:20] if base_phone else None),
                whatsapp_jid=str(user_id),
                interest="General",
                last_message=message,
                last_message_sender="user",
                last_message_preview=message[:500],
                conversation_count=1,
            )
        db.add(lead)
        db.commit()
        db.refresh(lead)

    try:
        from services.evidence_engine import link_unassigned_evidence_for_lead

        linked_count = link_unassigned_evidence_for_lead(db, company_id, lead.id, str(user_id))
        if linked_count:
            db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Skipped auto-reply evidence linking failed for company=%s user=%s: %s", company_id, user_id, exc)

    return lead


def _persist_skipped_auto_reply_inbound(db: Session, company_id: str, user_id: str, message: str, external_message_id: Optional[str], reason: str) -> str:
    internal_id = str(uuid.uuid4())
    save_message(db, company_id, user_id, "user", message, internal_id, "incoming", external_message_id)
    _ensure_lead_for_skipped_auto_reply(db, company_id, user_id, message)
    _record_auto_reply_skip(db, company_id, user_id, internal_id, reason)
    try:
        from services.workspace_suggestion_service import create_workspace_suggestion_for_message

        create_workspace_suggestion_for_message(db, company_id, user_id, internal_id, reason)
    except Exception as exc:
        db.rollback()
        log.warning("Workspace suggested reply generation failed for message %s: %s", internal_id, exc)
    return internal_id


# ─────────────────────────────────────────────────
# 🚀 ROUTES
# ─────────────────────────────────────────────────


@app.get("/health")
def health():
    """Liveness only: the process can answer an HTTP request."""
    return {"status": "ok", "version": "3.0.0"}


def _readiness_payload() -> tuple[dict, bool]:
    """Build a credential-free readiness result shared by public/admin views."""
    from database import get_database_runtime_summary
    from services.conversation_engine_config import (
        get_external_api_response_engine,
        get_whatsapp_response_engine,
    )
    from rate_limiter import get_rate_limiter_health
    from services.velor_chat_v2 import get_provider_health

    try:
        summary = get_database_runtime_summary(require_migration_head=True)
        database_ready = bool(summary.get("schema_compatible"))
        database_status = "compatible" if database_ready else "incompatible"
    except Exception as exc:
        log.warning("Readiness database check failed: %s", exc.__class__.__name__)
        summary = {}
        database_ready = False
        database_status = "error"

    engine_version = get_public_web_chat_engine()
    whatsapp_engine_version = get_whatsapp_response_engine()
    external_api_engine_version = get_external_api_response_engine()
    provider = get_provider_health()
    rate_limiter_health = get_rate_limiter_health(force_probe=True)
    fallback_ready = engine_version == "v2"
    require_provider = (
        ENV in {"verification", "staging", "production"}
        or os.getenv("REQUIRE_AI_PROVIDER_READY", "false").strip().casefold() == "true"
    )
    ai_ready = provider["provider_available"] if require_provider else (provider["provider_available"] or fallback_ready)
    release_engine_ready = (
        engine_version == "v2"
        and whatsapp_engine_version == "v2"
        and external_api_engine_version == "v2"
        if ENV in {"verification", "staging", "production"}
        else engine_version in {"v1", "v2"}
        and whatsapp_engine_version in {"v1", "v2"}
        and external_api_engine_version in {"v1", "v2"}
    )
    ready = (
        database_ready
        and release_engine_ready
        and ai_ready
        and rate_limiter_health["ready"]
    )
    status = "ready" if ready and provider["provider_available"] else ("degraded" if ready else "not_ready")
    return {
        "status": status,
        "database": database_status,
        "engine_version": engine_version,
        "whatsapp_engine_version": whatsapp_engine_version,
        "external_api_engine_version": external_api_engine_version,
        "provider_available": provider["provider_available"],
        "fallback_available": fallback_ready,
        "provider_required": require_provider,
        "rate_limiter_mode": rate_limiter_health["mode"],
        "redis_available": rate_limiter_health["redis_available"],
        "redis_required": rate_limiter_health["required"],
        "details": {
            "database": summary,
            "provider": provider,
            "rate_limiter": rate_limiter_health,
        },
    }, ready


@app.get("/ready")
def readiness():
    """Public readiness probe with only operational, non-sensitive fields."""
    payload, ready = _readiness_payload()
    public_payload = {key: value for key, value in payload.items() if key != "details"}
    return JSONResponse(status_code=200 if ready else 503, content=public_payload)


@app.get("/api/v1/admin/readiness")
def admin_readiness(current_user: dict = Depends(_get_current_user)):
    """Authenticated sanitized diagnostics; credentials and prompts are absent."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    payload, ready = _readiness_payload()
    payload["company_id"] = current_user["company_id"]
    return JSONResponse(status_code=200 if ready else 503, content=payload)


# ── Auth ──────────────────────────────────────────


@app.post("/signup")
@limiter.limit("5/minute")
def signup(request: Request, data: SignupData, db: Session = Depends(get_db)):
    email_clean = data.email.lower().strip()

    existing = (
        db.query(Company)
        .filter(
            Company.email == email_clean,
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="هذا البريد الإلكتروني مسجل بالفعل ⚠️")

    cid = f"company_{secrets.token_hex(4)}"
    raw_key = generate_api_key()

    create_company(
        db=db,
        company_id=cid,
        company_name=data.company_name,
        email=email_clean,
        password=data.password,
        api_key=raw_key,
        role="tenant",
        # Public signup never grants paid entitlements. Plan changes require a
        # trusted administrative or verified billing workflow.
        plan="FREE",
        terms_accepted_at=datetime.now(timezone.utc),
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
    )
    write_audit_log(
        db,
        "SIGNUP",
        company_id=cid,
        ip_address=_get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
        detail=f"email={email_clean} plan=FREE",
    )

    return {
        "success": True,
        "message": "تم إنشاء حساب شركتك بنجاح! 🎉",
        "company_id": cid,
        "api_key": raw_key,
        "note": "⚠️ احتفظ بمفتاح الـ API Key في مكان آمن، لن يظهر مرة أخرى!",
    }


@app.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    ua = request.headers.get("User-Agent", "")[:300]

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = body.get("email", "").lower().strip()
        password = body.get("password", "")
    else:
        form = await request.form()
        email = form.get("username", "").lower().strip()
        password = form.get("password", "")

    company = (
        db.query(Company)
        .filter(
            Company.email == email,
            Company.is_deleted == False,
        )
        .first()
    )

    if not timing_safe_verify(password, company.password if company else None):
        write_audit_log(db, "LOGIN_FAILURE", ip_address=ip, user_agent=ua, detail=f"email={email}")
        return JSONResponse(status_code=401, content={"success": False, "message": "بيانات الدخول غير صحيحة"})

    role = company.role
    access_token = _create_access_token(company.company_id, role)
    refresh_raw = create_refresh_token(db, company.company_id)

    write_audit_log(db, "LOGIN_SUCCESS", company_id=company.company_id, ip_address=ip, user_agent=ua)

    response = JSONResponse(
        content={
            "success": True,
            "company_id": company.company_id,
            "role": role,
            "plan": company.plan,
        }
    )

    cookie_kwargs = _cookie_security()
    response.set_cookie(key="access_token", value=access_token, max_age=ACCESS_TOKEN_MINUTES * 60, **cookie_kwargs)
    response.set_cookie(key="refresh_token", value=refresh_raw, max_age=30 * 24 * 3600, **cookie_kwargs)
    return response


@app.post("/auth/google")
@limiter.limit("5/minute")
def google_auth(request: Request, data: GoogleAuthData, db: Session = Depends(get_db)):
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id or client_id == "YOUR_GOOGLE_CLIENT_ID":
        raise HTTPException(status_code=503, detail="تسجيل الدخول عبر Google غير مُعد حاليًا")

    try:
        idinfo = id_token.verify_oauth2_token(data.token, google_requests.Request(), client_id)
        if idinfo.get("email_verified") is not True:
            raise HTTPException(status_code=400, detail="يجب أن يكون بريد Google موثقًا")
        email = idinfo["email"].lower().strip()
        google_subject = str(idinfo.get("sub") or "").strip()
        if not google_subject:
            raise HTTPException(status_code=400, detail="رمز هوية Google يفتقد معرّف الحساب")
        name = idinfo.get("name", "Google User")
    except ValueError:
        raise HTTPException(status_code=400, detail="رمزهوية جوجل غير صالح ⚠️")

    company = (
        db.query(Company)
        .filter(
            Company.google_subject == google_subject,
            Company.auth_provider == "google",
            Company.is_deleted == False,
        )
        .first()
    )

    if not company:
        email_owner = db.query(Company).filter(Company.email == email, Company.is_deleted == False).first()
        if email_owner:
            # Never merge identities by matching email alone. A password
            # account must be linked through an explicit, authenticated flow.
            raise HTTPException(
                status_code=409,
                detail="هذا البريد مرتبط بحساب قائم. سجّل الدخول بالطريقة الأصلية ثم اربط Google من الإعدادات.",
            )

        if data.terms_accepted is not True:
            raise HTTPException(
                status_code=400,
                detail="يجب الموافقة على شروط الاستخدام وسياسة الخصوصية لإنشاء حساب جديد.",
            )

        # Auto Signup for Google Auth
        cid = f"company_{secrets.token_hex(4)}"
        raw_key = generate_api_key()
        random_password = secrets.token_urlsafe(32)  # Handled safely inside create_company

        create_company(
            db=db,
            company_id=cid,
            company_name=name,
            email=email,
            password=random_password,
            api_key=raw_key,
            role="tenant",
            plan="FREE",
            auth_provider="google",
            google_subject=google_subject,
            terms_accepted_at=datetime.now(timezone.utc),
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
        )
        write_audit_log(
            db,
            "SIGNUP_GOOGLE",
            company_id=cid,
            ip_address=_get_client_ip(request),
            user_agent=request.headers.get("User-Agent", "")[:300],
            detail=f"email={email} plan=FREE",
        )

        company = db.query(Company).filter(Company.email == email).first()
        is_new_user = True
        new_api_key = raw_key
    else:
        is_new_user = False
        new_api_key = None

    role = company.role
    access_token = _create_access_token(company.company_id, role)
    refresh_raw = create_refresh_token(db, company.company_id)

    ip = _get_client_ip(request)
    ua = request.headers.get("User-Agent", "")[:300]
    write_audit_log(db, "LOGIN_GOOGLE_SUCCESS", company_id=company.company_id, ip_address=ip, user_agent=ua)

    response_data = {
        "success": True,
        "company_id": company.company_id,
        "role": role,
        "plan": company.plan,
        "is_new_user": is_new_user,
    }
    if is_new_user:
        response_data["api_key"] = new_api_key
        response_data["message"] = "تم إنشاء حساب شركتك بنجاح! 🎉"
        response_data["note"] = "⚠️ احتفظ بمفتاح الـ API Key في مكان آمن، لن يظهر مرة أخرى!"

    response = JSONResponse(content=response_data)

    cookie_kwargs = _cookie_security()
    response.set_cookie(key="access_token", value=access_token, max_age=ACCESS_TOKEN_MINUTES * 60, **cookie_kwargs)
    response.set_cookie(key="refresh_token", value=refresh_raw, max_age=30 * 24 * 3600, **cookie_kwargs)
    return response


@app.post("/token/refresh")
@limiter.limit("10/minute")
def token_refresh(request: Request, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    result = rotate_refresh_token(db, refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="Refresh token invalid or expired")

    new_refresh_raw, company = result
    company_id = company.company_id

    new_access = _create_access_token(company.company_id, company.role)
    write_audit_log(db, "TOKEN_ROTATED", company_id=company_id, ip_address=_get_client_ip(request))

    response = JSONResponse(content={"success": True})

    cookie_kwargs = _cookie_security()
    response.set_cookie(key="access_token", value=new_access, max_age=ACCESS_TOKEN_MINUTES * 60, **cookie_kwargs)
    response.set_cookie(key="refresh_token", value=new_refresh_raw, max_age=30 * 24 * 3600, **cookie_kwargs)
    return response


@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        revoke_refresh_token(db, refresh_token)

    response = JSONResponse(content={"success": True, "message": "Logged out successfully"})
    cookie_kwargs = _cookie_security()

    # Must match the exact attributes (including httponly and path) to successfully delete the cookie
    response.delete_cookie(
        "access_token", secure=cookie_kwargs["secure"], samesite=cookie_kwargs["samesite"], httponly=cookie_kwargs.get("httponly", True), path="/"
    )
    response.delete_cookie(
        "refresh_token", secure=cookie_kwargs["secure"], samesite=cookie_kwargs["samesite"], httponly=cookie_kwargs.get("httponly", True), path="/"
    )
    return response


@app.post("/token/revoke")
async def token_revoke(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(_get_current_user),
):
    # Read from cookie (primary) or fall back to JSON body
    raw_token = request.cookies.get("refresh_token")
    if not raw_token:
        try:
            body_data = await request.json()
            raw_token = body_data.get("refresh_token")
        except Exception:
            # If body isn't JSON or can't be read, fall back to empty
            raw_token = None

    if not raw_token:
        raise HTTPException(status_code=400, detail="No refresh token provided")

    found = revoke_refresh_token(db, raw_token, company_id=current_user["company_id"])
    if not found:
        raise HTTPException(status_code=404, detail="Token not found or does not belong to your account")

    write_audit_log(
        db,
        "TOKEN_REVOKED",
        company_id=current_user["company_id"],
        ip_address=_get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
    )
    return {"success": True, "message": "Token revoked"}


# ── Company ────────────────────────────────────────


@app.get("/me")
def me(db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)):
    company = (
        db.query(Company)
        .filter(
            Company.company_id == current_user["company_id"],
            Company.is_deleted == False,
        )
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "company_id": company.company_id,
        "company_name": company.company_name,
        "email": company.email,
        "role": company.role,
        "plan": company.plan,
    }


@app.get("/whatsapp/settings/alerts")
def get_alert_settings(db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)):
    company = (
        db.query(Company)
        .filter(
            Company.company_id == current_user["company_id"],
            Company.is_deleted == False,
        )
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "success": True,
        "settings": {
            "is_alerts_enabled": company.is_alerts_enabled,
            "alert_whatsapp_number": company.alert_whatsapp_number,
        },
    }


@app.put("/whatsapp/settings/alerts")
@app.patch("/whatsapp/settings/alerts")
def update_alert_settings(request: Request, data: AlertSettingsData, db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)):
    company = (
        db.query(Company)
        .filter(
            Company.company_id == current_user["company_id"],
            Company.is_deleted == False,
        )
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.is_alerts_enabled = data.is_alerts_enabled
    company.alert_whatsapp_number = data.alert_whatsapp_number
    db.commit()

    write_audit_log(
        db,
        "SETTINGS_UPDATE",
        company_id=current_user["company_id"],
        ip_address=_get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
    )

    return {"success": True, "message": "تم تحديث الإعدادات بنجاح!"}


@app.get("/whatsapp/settings")
def get_whatsapp_settings(db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)):
    from database import get_company_knowledge, KnowledgeSource
    from services.product_context_service import normalize_products_data
    from services.velor_chat_v2 import get_provider_health

    knowledge = get_company_knowledge(db, current_user["company_id"])
    company = db.query(Company).filter(Company.company_id == current_user["company_id"], Company.is_deleted == False).first()
    if not knowledge:
        return {"success": True, "knowledge": {}}
    raw_knowledge_base = knowledge.pop("knowledge_base", "") or ""
    knowledge["has_knowledge"] = bool(raw_knowledge_base.strip())
    knowledge["knowledge_size"] = len(raw_knowledge_base)
    catalog = normalize_products_data(knowledge.get("products_data"))
    knowledge["catalog_status"] = {
        "total_records": len(catalog),
        "priced_records": len([product for product in catalog if product.price is not None]),
        "active_records": len(catalog),
    }
    knowledge["system_prompt_max_chars"] = COMPANY_SYSTEM_PROMPT_MAX_CHARS
    knowledge["bot_auto_reply_enabled"] = getattr(company, "bot_auto_reply_enabled", True) if company else True
    source_rows = db.query(KnowledgeSource).filter(
        KnowledgeSource.company_id == current_user["company_id"],
        KnowledgeSource.is_deleted == False,
    ).all()
    knowledge["knowledge_source_status"] = {
        "total": len(source_rows),
        "active": len([row for row in source_rows if row.active and row.status == "processed"]),
        "error": len([row for row in source_rows if row.status == "error"]),
    }
    provider_health = get_provider_health()
    provider_health.setdefault("provider_name", provider_health.get("provider"))
    provider_health.setdefault("last_success_at", provider_health.get("last_successful_provider_call"))
    return {
        "success": True,
        "knowledge": knowledge,
        "engine": {**provider_health, "selected_public_engine": get_public_web_chat_engine()},
    }


class SettingsUpdateData(BaseModel):
    company_name: Optional[str] = ""
    industry: Optional[str] = ""
    tone: Optional[str] = "professional"
    welcome_message: Optional[str] = ""
    system_prompt: Optional[str] = ""
    products_data: Optional[str] = None
    language: Optional[str] = "Arabic"
    lead_collection: Optional[bool] = True

    @field_validator("system_prompt")
    @classmethod
    def _validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        return validate_company_system_prompt(v)

    @model_validator(mode="before")
    @classmethod
    def _handle_products_alias(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if "products" in values and "products_data" not in values:
                val = values["products"]
                if isinstance(val, (list, dict)):
                    values["products_data"] = json.dumps(val, ensure_ascii=False)
                elif isinstance(val, str) or val is None:
                    values["products_data"] = val
            if "products_data" in values and isinstance(values["products_data"], (list, dict)):
                values["products_data"] = json.dumps(values["products_data"], ensure_ascii=False)
        return values



@app.post("/whatsapp/settings/update")
def update_whatsapp_settings(data: SettingsUpdateData, db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)):
    from database import update_company_knowledge, CompanyKnowledge
    from services.settings_preservation import validate_catalog_replacement
    try:
        company_id = current_user["company_id"]
        products_provided = ("products_data" in data.model_fields_set or "products" in data.model_fields_set)

        products_data_to_save = None
        if products_provided and data.products_data is not None:
            existing_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
            existing_products_raw = existing_k.products_data if existing_k else None

            validate_catalog_replacement(existing_products_raw, data.products_data)
            products_data_to_save = data.products_data

        system_prompt_provided = ("system_prompt" in data.model_fields_set and data.system_prompt)
        system_prompt_to_save = data.system_prompt if system_prompt_provided else None

        update_company_knowledge(
            db=db,
            company_id=company_id,
            system_prompt=system_prompt_to_save,
            products_data=products_data_to_save,
            welcome_message=data.welcome_message or "",
            industry=data.industry or "",
            tone=data.tone or "professional",
            language=data.language or "Arabic",
            lead_collection=data.lead_collection if data.lead_collection is not None else True,
            company_name=data.company_name or ""
        )
        from services.workspace_suggestion_service import invalidate_company_suggestions
        invalidate_company_suggestions(db, company_id, "catalog_or_policy_changed")
        db.commit()
        try:
            from services.product_context_service import normalize_products_data
            from services.pilot_telemetry_service import record_pilot_event

            catalog = normalize_products_data(products_data_to_save) if products_data_to_save is not None else []
            if catalog:
                record_pilot_event(
                    db,
                    event_name="catalog_first_valid_product",
                    company_id=company_id,
                    actor_type="owner",
                    entity_id=company_id,
                    source="settings",
                )
            record_pilot_event(
                db,
                event_name="merchant_onboarding_completed",
                company_id=company_id,
                actor_type="owner",
                entity_id=company_id,
                source="settings",
                metadata={"estimated": False},
            )
        except Exception as telemetry_exc:
            db.rollback()
            log.warning("Onboarding telemetry write failed category=%s", telemetry_exc.__class__.__name__)
        return {"success": True, "message": "تم تحديث إعدادات البوت بنجاح"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        log.warning("Settings update failed for company=%s category=%s", current_user.get("company_id"), exc.__class__.__name__)
        raise HTTPException(status_code=500, detail="Failed to update settings safely.")


@app.get("/api/company/bot/auto-reply")
def get_company_auto_reply(db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "success": True,
        "bot_auto_reply_enabled": getattr(company, "bot_auto_reply_enabled", True),
    }


@app.post("/api/company/bot/auto-reply")
def update_company_auto_reply(data: BotAutoReplyUpdate, db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.bot_auto_reply_enabled = data.enabled
    db.commit()

    return {
        "success": True,
        "bot_auto_reply_enabled": company.bot_auto_reply_enabled,
    }


# --- VELOR WEB CHAT ENDPOINTS ---

from datetime import datetime, timezone, timedelta
from jose import JWTError, jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Security
from pydantic import BaseModel, Field
from typing import Optional
from database import Company, CompanyKnowledge, Lead, Message, MessageEvent, save_message
from services.processing_claim import acquire_inbound_processing_claim, finalize_inbound_processing_claim, ClaimResult
from rate_limiter import is_rate_limited
from brain import get_ai_response

security_bearer = HTTPBearer(auto_error=False)

class WebChatStatusUpdate(BaseModel):
    enabled: bool

class PublicChatRequest(BaseModel):
    # Length remains an explicit route-level 400 contract for backwards
    # compatibility; Pydantic would otherwise convert oversize input to 422.
    message: str
    client_message_id: str = Field(..., min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")

def _create_visitor_token(company_id: str, visitor_id: str) -> str:
    """Generates a signed, bounded-expiry visitor session token."""
    # Strict fail-closed verification
    if not JWT_SECRET or len(JWT_SECRET) < 32:
        raise HTTPException(status_code=500, detail="Invalid JWT configuration")
    if ENV == "production":
        if JWT_SECRET in FORBIDDEN_PRODUCTION_SECRETS or "test" in JWT_SECRET.lower() or "default" in JWT_SECRET.lower():
            raise HTTPException(status_code=500, detail="Invalid JWT configuration in production")

    now = datetime.now(timezone.utc)
    payload = {
        "iss": "velor-webchat",
        "aud": "velor-public-client",
        "sub": visitor_id,
        "company_id": company_id,
        "role": "visitor",
        "iat": now,
        "exp": now + timedelta(days=7) # Bounded to 7 days
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _get_current_visitor(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> dict:
    """Validates the visitor JWT, ensuring company scope and visitor scope are intact."""
    if not JWT_SECRET or len(JWT_SECRET) < 32:
        raise HTTPException(status_code=500, detail="Invalid JWT configuration")
    if ENV == "production":
        if JWT_SECRET in FORBIDDEN_PRODUCTION_SECRETS or "test" in JWT_SECRET.lower() or "default" in JWT_SECRET.lower():
            raise HTTPException(status_code=500, detail="Invalid JWT configuration in production")

    if not credentials:
        raise HTTPException(status_code=401, detail="Missing visitor session token")
    
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience="velor-public-client",
            issuer="velor-webchat"
        )
        if payload.get("role") != "visitor":
            raise HTTPException(status_code=401, detail="Invalid token role")
        
        visitor_id = payload.get("sub")
        company_id = payload.get("company_id")
        
        if not visitor_id or not company_id:
            raise HTTPException(status_code=401, detail="Malformed session token")
            
        return {
            "visitor_id": visitor_id,
            "company_id": company_id
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

def generate_unique_public_slug(db: Session) -> str:
    import uuid
    for _ in range(10):
        slug = f"chat-{uuid.uuid4().hex[:16]}"
        exists = db.query(Company).filter(Company.public_chat_slug == slug).first()
        if not exists:
            return slug
    return f"chat-{uuid.uuid4().hex}"

@app.get("/api/company/bot/web-chat")
def get_company_web_chat(db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Generate public chat slug if it is missing
    if not company.public_chat_slug:
        company.public_chat_slug = generate_unique_public_slug(db)
        db.commit()
        
    return {
        "success": True,
        "is_web_chat_enabled": getattr(company, "is_web_chat_enabled", False),
        "public_chat_slug": company.public_chat_slug
    }

@app.post("/api/company/bot/web-chat")
def update_company_web_chat(data: WebChatStatusUpdate, db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.is_web_chat_enabled = data.enabled
    
    # Generate public chat slug if it is missing
    if not company.public_chat_slug:
        company.public_chat_slug = generate_unique_public_slug(db)
        
    db.commit()

    return {
        "success": True,
        "is_web_chat_enabled": company.is_web_chat_enabled,
        "public_chat_slug": company.public_chat_slug
    }

@app.post("/api/public/companies/{slug}/session")
def init_public_session(request: Request, slug: str, db: Session = Depends(get_db)):
    company = (
        db.query(Company)
        .filter(Company.public_chat_slug == slug, Company.is_deleted == False)
        .with_for_update()
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
        
    if not company.is_web_chat_enabled:
        raise HTTPException(status_code=400, detail="Web chat is disabled for this company")

    client_host = _get_client_ip(request)
    # Public pages are often shared by many visitors behind one NAT. Keep a
    # bounded protection limit without treating normal refreshes and a few
    # simultaneous tabs as an attack. Deployments can override this value.
    session_ip_limit = int(os.getenv("PUBLIC_CHAT_SESSION_IP_LIMIT_PER_MINUTE", "30"))
    session_tenant_limit = int(os.getenv("PUBLIC_CHAT_SESSION_TENANT_LIMIT_PER_MINUTE", "30"))
    if is_rate_limited(db, company.company_id, f"session_ip:{client_host}", limit=session_ip_limit, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many session requests. Try again later.")
    if is_rate_limited(db, company.company_id, f"session_tenant:{company.company_id}", limit=session_tenant_limit, window_seconds=60):
        raise HTTPException(status_code=429, detail="This chat is temporarily busy. Try again shortly.")

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    session_count = (
        db.query(Lead)
        .filter(
            Lead.company_id == company.company_id,
            Lead.channel_type == "VELOR_WEB_CHAT",
            Lead.created_at >= month_start,
            Lead.is_deleted == False,
        )
        .count()
    )
    plan_limit = get_limits(company.plan).monthly_leads
    hard_cap = int(os.getenv("PUBLIC_CHAT_HARD_SESSION_CAP_PER_MONTH", "10000"))
    allowed = check_lead_quota(company.plan, session_count)
    if plan_limit == -1:
        allowed = session_count < hard_cap
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="This workspace has reached its monthly public-chat session limit.",
        )
        
    # Generate opaque random visitor ID
    visitor_id = f"wc_v_{uuid.uuid4().hex[:12]}"
    
    # Create lead in DB (channel-agnostic, phone=None, external_customer_id=visitor_id)
    lead = Lead(
        company_id=company.company_id,
        name="عميل محتمل",
        phone=None,
        whatsapp_number=None,
        whatsapp_jid=None,
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=visitor_id,
        status="new",
        is_test=(
            company.company_id.startswith("velor_demo_")
            or str(company.email or "").endswith("@demo.local")
        ),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Sign JWT token
    token = _create_visitor_token(company.company_id, visitor_id)
    
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company.company_id).first()
    welcome_message = knowledge.welcome_message if knowledge else "مرحباً بك! كيف يمكنني مساعدتك اليوم؟"
    suggested_questions_raw = knowledge.suggested_questions if knowledge else ""
    suggested_questions = [q.strip() for q in suggested_questions_raw.split("\n") if q.strip()] if suggested_questions_raw else []
    
    return {
        "token": token,
        "visitor_id": visitor_id,
        "company_name": company.company_name,
        "welcome_message": welcome_message,
        "suggested_questions": suggested_questions
    }

@app.get("/api/public/companies/{slug}/session")
def get_public_session(
    slug: str,
    visitor: dict = Depends(_get_current_visitor),
    db: Session = Depends(get_db)
):
    visitor_id = visitor["visitor_id"]
    company_id = visitor["company_id"]
    
    # Find company by slug
    company = db.query(Company).filter(Company.public_chat_slug == slug, Company.is_deleted == False).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
        
    # Enforce company scope to prevent cross-tenant token reuse
    if company.company_id != company_id:
        raise HTTPException(status_code=403, detail="Access denied")
        
    if not company.is_web_chat_enabled:
        raise HTTPException(status_code=400, detail="Web chat is disabled")
        
    # Find lead to make sure they exist
    lead = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.channel_type == "VELOR_WEB_CHAT",
        Lead.external_customer_id == visitor_id,
        Lead.is_deleted == False
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Retrieve messages for this visitor ordered by creation time
    messages_query = db.query(Message).filter(
        Message.company_id == company_id,
        Message.user_id == visitor_id,
        Message.is_deleted == False
    ).order_by(Message.created_at.asc()).all()
    
    # Public presentation is persisted in the canonical message.created event,
    # not recreated from the mutable assistant text.  That keeps reloads,
    # retries, and a second browser context consistent without exposing traces.
    outgoing_ids = [message.internal_message_id for message in messages_query if message.sender == "assistant"]
    response_by_message_id = {}
    if outgoing_ids:
        for event in db.query(SystemEvent).filter(
            SystemEvent.company_id == company_id,
            SystemEvent.event_type == "message.created",
            SystemEvent.entity_id.in_(outgoing_ids),
        ).all():
            try:
                payload = json.loads(event.payload or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(payload.get("response"), dict):
                response_by_message_id[event.entity_id] = payload["response"]

    conversations = [
        {
            "id": msg.public_message_id,
            "sender": msg.sender,
            "direction": msg.direction,
            "message": msg.message,
            "delivery_status": msg.delivery_status,
            "created_at": _iso_utc(msg.created_at),
            "client_message_id": msg.wa_message_id.split(':')[-1] if (msg.wa_message_id and msg.wa_message_id.startswith('wc:')) else None,
            **({"response": response_by_message_id[msg.internal_message_id]} if msg.internal_message_id in response_by_message_id else {}),
        }
        for msg in messages_query
    ]
    
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    welcome_message = knowledge.welcome_message if knowledge else "مرحباً بك! كيف يمكنني مساعدتك اليوم؟"
    suggested_questions_raw = knowledge.suggested_questions if knowledge else ""
    suggested_questions = [q.strip() for q in suggested_questions_raw.split("\n") if q.strip()] if suggested_questions_raw else []
    
    return {
        "visitor_id": visitor_id,
        "company_name": company.company_name,
        "welcome_message": welcome_message,
        "suggested_questions": suggested_questions,
        "conversations": conversations,
        "is_paused": lead.is_paused
    }


def _find_public_reply_for_inbound(db: Session, company_id: str, visitor_id: str, inbound_internal_id: str):
    """Return only the assistant reply explicitly linked to this inbound turn."""
    from services.public_chat_turn_service import find_reply_for_inbound

    inbound = (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.internal_message_id == inbound_internal_id,
            Message.direction == "incoming",
        )
        .first()
    )
    if inbound is not None:
        return find_reply_for_inbound(
            db,
            company_id=company_id,
            user_id=visitor_id,
            inbound=inbound,
        )
    return None, None

@app.post("/api/public/chat")
async def public_chat_send(
    request: Request,
    data: PublicChatRequest,
    background_tasks: BackgroundTasks,
    visitor: dict = Depends(_get_current_visitor),
    db: Session = Depends(get_db)
):
    visitor_id = visitor["visitor_id"]
    company_id = visitor["company_id"]
    
    # Rate limiters
    public_ip_limit = int(os.getenv("PUBLIC_CHAT_IP_LIMIT_PER_MINUTE", "20"))
    public_visitor_limit = int(os.getenv("PUBLIC_CHAT_VISITOR_LIMIT_PER_MINUTE", "10"))
    public_tenant_limit = int(os.getenv("PUBLIC_CHAT_TENANT_LIMIT_PER_MINUTE", "60"))
    client_host = _get_client_ip(request)
    if is_rate_limited(db, company_id, f"ip:{client_host}", limit=public_ip_limit, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many requests from this IP")
    if is_rate_limited(db, company_id, visitor_id, limit=public_visitor_limit, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many requests")
    if is_rate_limited(db, company_id, f"tenant_limit:{company_id}", limit=public_tenant_limit, window_seconds=60):
        raise HTTPException(status_code=429, detail="Server busy, try again later")
        
    message_text = data.message.strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(message_text) > 1000:
        raise HTTPException(status_code=400, detail="Message is too long")
        
    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company or not company.is_web_chat_enabled:
        raise HTTPException(status_code=400, detail="Web chat is not active")
        
    lead = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.channel_type == "VELOR_WEB_CHAT",
        Lead.external_customer_id == visitor_id,
        Lead.is_deleted == False
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Conversation session not found")
        
    # Channel-scoped idempotency key
    wa_message_id = f"wc:{company_id}:{data.client_message_id}"
    use_v2 = get_public_web_chat_engine() == "v2"
    # V2 keeps its idempotency lease in this open transaction until the final
    # executor accepts the turn.  No inbound row or observable side effect is
    # committed before the response has been safely planned.
    defer_v2_projection = use_v2 and (not lead.is_paused) and getattr(company, "bot_auto_reply_enabled", True)
    
    claim_result, inc_msg = acquire_inbound_processing_claim(
        db,
        company_id,
        visitor_id,
        wa_message_id,
        message_text,
        defer_side_effects=defer_v2_projection,
        commit=not defer_v2_projection,
    )
    
    if claim_result == ClaimResult.ALREADY_PROCESSING:
        return JSONResponse(status_code=202, content={"status": "processing", "message": "Already processing message"})
        
    if claim_result == ClaimResult.COMPLETED:
        existing_reply, existing_response = _find_public_reply_for_inbound(
            db, company_id, visitor_id, inc_msg.internal_message_id
        )
        # V1 rollback messages predate explicit reply linkage.  Keep this
        # compatibility fallback isolated to the rollback engine; V2 always
        # uses the linked event above.
        if existing_reply is None and get_public_web_chat_engine() == "v1":
            existing_reply = db.query(Message).filter(
                Message.company_id == company_id,
                Message.user_id == visitor_id,
                Message.direction == "outgoing",
                Message.sender == "assistant",
                Message.id > inc_msg.id,
            ).order_by(Message.id.asc()).first()
        
        return {
            "status": "completed",
            "reply": existing_reply.message if existing_reply else None,
            "id": existing_reply.public_message_id if existing_reply else None,
            "duplicate": True,
            **({"response": existing_response} if existing_response else {}),
        }
        
    if claim_result in (ClaimResult.INTENTIONALLY_SKIPPED, ClaimResult.UNKNOWN_UNSAFE):
        return {"status": "skipped", "reply": None, "duplicate": True}
        
    inc_internal_id = inc_msg.internal_message_id if inc_msg else None
    processing_claim_attempt = inc_msg.processing_attempts if inc_msg else None
    
    monthly_messages, _ = get_monthly_usage(db, company_id)
    if not check_message_quota(company.plan, monthly_messages):
        if use_v2:
            db.rollback()
        elif inc_internal_id:
            finalize_inbound_processing_claim(
                db,
                inc_internal_id,
                "skipped",
                expected_attempts=processing_claim_attempt,
            )
        return {
            "status": "quota_exceeded",
            "reply": "تم الوصول للحد الشهري من الرسائل. يرجى ترقية الباقة لاستكمال الردود الآلية.",
            "id": None
        }
        
    auto_reply_allowed = (not lead.is_paused) and getattr(company, "bot_auto_reply_enabled", True)
    
    if auto_reply_allowed:
        try:
            try:
                reply_timeout_seconds = float(os.getenv("PUBLIC_CHAT_REPLY_TIMEOUT_SECONDS", "40"))
            except (TypeError, ValueError):
                reply_timeout_seconds = 40.0

            public_response = None
            public_msg_id = None
            if use_v2:
                from services.public_chat_turn_service import (
                    cancel_persisted_auto_reply,
                    current_auto_reply_block_reason,
                )
                from services.v2_turn_use_case import execute_v2_turn
                response_coro = execute_v2_turn(
                    db=db,
                    company=company,
                    lead=lead,
                    source_message=inc_msg,
                    company_id=company_id,
                    lead_id=lead.id,
                    user_id=visitor_id,
                    customer_text=message_text,
                    inbound_internal_id=inc_internal_id,
                    processing_claim_attempt=processing_claim_attempt,
                    background_tasks=background_tasks,
                    channel_type="VELOR_WEB_CHAT",
                    source_route="/api/public/chat",
                    enforce_auto_reply_guard=True,
                )
                if reply_timeout_seconds > 0:
                    v2_turn = await asyncio.wait_for(response_coro, timeout=reply_timeout_seconds)
                else:
                    v2_turn = await response_coro

                v2_res = v2_turn["result"]
                reply = v2_res["answer_text"]
                trace = v2_turn["trace"]
                public_response = v2_turn.get("response_envelope")
                persisted_turn = v2_turn["persisted"]

                if not persisted_turn:
                    return JSONResponse(
                        status_code=409,
                        content={"status": "superseded", "message": "Message processing was superseded; retry safely"},
                    )
                if persisted_turn.get("auto_reply_skipped"):
                    return {
                        "status": "skipped",
                        "reply": None,
                        "id": None,
                        "reason": persisted_turn.get("reason"),
                    }

                internal_id = persisted_turn["internal_id"]
                lead_id = persisted_turn["lead_id"]
                public_msg_id = persisted_turn["public_message_id"]
                ai_handoff_pause = bool(
                    (trace.get("lead_to_save") or {}).get("is_paused") is True
                    and (trace.get("conversation_action") or {}).get("type") == "START_HUMAN_HANDOFF"
                )
                late_block_reason = current_auto_reply_block_reason(
                    db,
                    company_id=company_id,
                    lead_id=lead_id,
                    inbound_internal_id=inc_internal_id,
                    allow_ai_handoff_pause=ai_handoff_pause,
                )
                if late_block_reason:
                    cancel_persisted_auto_reply(
                        db,
                        company_id=company_id,
                        inbound_internal_id=inc_internal_id,
                        outbound_internal_id=internal_id,
                        reason=late_block_reason,
                    )
                    return {
                        "status": "skipped",
                        "reply": None,
                        "id": None,
                        "reason": late_block_reason,
                    }
                trace["commercial_persistence_result"] = "persisted"
            else:
                response_coro = get_ai_response(
                    db=db,
                    user_input=message_text,
                    user_id=visitor_id,
                    company_id=company_id,
                    background_tasks=background_tasks,
                    incoming_wa_message_id=wa_message_id,
                    persist_incoming=False,
                    processing_claim_internal_id=inc_internal_id,
                    processing_claim_attempt=processing_claim_attempt,
                )
                if reply_timeout_seconds > 0:
                    reply, internal_id = await asyncio.wait_for(response_coro, timeout=reply_timeout_seconds)
                else:
                    reply, internal_id = await response_coro
            
            if inc_internal_id and not use_v2:
                if not finalize_inbound_processing_claim(
                    db,
                    inc_internal_id,
                    "completed",
                    expected_attempts=processing_claim_attempt,
                ):
                    return JSONResponse(
                        status_code=409,
                        content={"status": "superseded", "message": "Message processing was superseded; retry safely"},
                    )
                
            if internal_id and not use_v2:
                msg = db.query(Message).filter(Message.internal_message_id == internal_id).first()
                if msg:
                    msg.delivery_status = "sent"
                    public_msg_id = msg.public_message_id
                    db.commit()

            return {
                "status": "completed",
                "reply": reply,
                "id": public_msg_id,
                # Additive V2 contract. Existing clients continue to consume
                # ``reply`` unchanged and never receive the internal trace.
                **({"response": public_response} if public_response else {}),
            }
            
        except asyncio.TimeoutError:
            log.warning(
                "Timed out generating Web Chat reply for company=%s visitor=%s client_message_id=%s",
                company_id,
                visitor_id,
                data.client_message_id,
            )
            if use_v2:
                db.rollback()
            elif inc_internal_id:
                finalize_inbound_processing_claim(
                    db,
                    inc_internal_id,
                    "failed",
                    expected_attempts=processing_claim_attempt,
                )
            raise HTTPException(status_code=504, detail="AI provider took too long; retry safely")
        except Exception as e:
            log.error("Failed to generate Web Chat reply: %s", e)
            if use_v2:
                db.rollback()
            elif inc_internal_id:
                finalize_inbound_processing_claim(
                    db,
                    inc_internal_id,
                    "failed",
                    expected_attempts=processing_claim_attempt,
                )
            raise HTTPException(status_code=500, detail="Internal server error")
    else:
        reason = "human_takeover_active" if lead.is_paused else "company_auto_reply_disabled"
        if inc_internal_id:
            finalize_inbound_processing_claim(
                db,
                inc_internal_id,
                "skipped",
                expected_attempts=processing_claim_attempt,
            )
            
        _record_auto_reply_skip(db, company_id, visitor_id, inc_internal_id, reason)
        try:
            from services.workspace_suggestion_service import create_workspace_suggestion_for_message
            create_workspace_suggestion_for_message(db, company_id, visitor_id, inc_internal_id, reason)
        except Exception as exc:
            log.warning("Workspace suggested reply failed: %s", exc)
            
        return {
            "status": "skipped",
            "reply": None,
            "id": inc_msg.public_message_id if inc_msg else None
        }


@app.post("/api/wizard/generate")
@limiter.limit("5/minute")
async def generate_wizard_prompt(
    request: Request,
    data: WizardData,
    db: Session = Depends(get_db),
    current_user: dict = Depends(_get_current_user),
):
    try:
        result = await generate_advanced_system_prompt(data.model_dump())
        return {"success": True, "data": result}
    except Exception as e:
        log.error("Wizard Generation failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate AI prompt. Please try again.")


@app.get("/companies-list")
def companies_list(
    db: Session = Depends(get_db),
    current_user: dict = Depends(_get_current_user),
):
    if current_user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="للأدمن فقط 🛑")
    rows = db.query(Company).filter(Company.is_deleted == False).all()
    return {
        "success": True,
        "companies": [{"company_id": c.company_id, "company_name": c.company_name, "plan": c.plan} for c in rows],
    }


@app.post("/rotate-api-key")
@limiter.limit("3/minute")
def rotate_api_key(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(_get_current_user),
):
    cid = current_user["company_id"]
    company = (
        db.query(Company)
        .filter(
            Company.company_id == cid,
            Company.is_deleted == False,
        )
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    new_raw = generate_api_key()
    company.api_key_hash = hash_api_key(new_raw)
    db.commit()

    write_audit_log(
        db,
        "API_KEY_ROTATION",
        company_id=cid,
        ip_address=_get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
        detail="Old key invalidated; new key issued",
    )
    return {
        "success": True,
        "api_key": new_raw,
        "note": "⚠️ المفتاح القديم تم إلغاؤه فوراً. احتفظ بهذا المفتاح في مكان آمن.",
    }


# ── Stats & Data ──────────────────────────────────
@app.post("/api/leads/{phone}/status")
@limiter.limit("20/minute")
def update_lead_status(
    request: Request, phone: str, data: LeadStatusUpdate, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)
):
    from sqlalchemy.sql import func
    from services.lead_service import transition_lead_status

    wa_num = normalize_whatsapp_number(phone)
    lead = db.query(Lead).filter(Lead.company_id == target_cid, (Lead.whatsapp_number == wa_num) | (Lead.phone == phone)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found in database")

    # Use the domain service to apply the change and cascade side-effects
    transition_lead_status(db, lead, data.status)
    db.commit()
    db.refresh(lead)

    write_audit_log(
        db,
        "LEAD_STATUS_UPDATE",
        company_id=target_cid,
        ip_address=_get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
        detail=f"phone={phone} status={data.status}",
    )

    lead_dict = {
        "status": lead.status,
        "stage": lead.stage,
        "is_hot_deal": lead.is_hot_deal,
        "needs_human_intervention": lead.needs_human_intervention,
        "ai_summary": lead.ai_summary,
        "lead_score": lead.lead_score,
    }
    if lead.intelligence_snapshot:
        lead_dict["intelligence_snapshot"] = {
            "why_summary": lead.intelligence_snapshot.why_summary,
            "next_best_action": lead.intelligence_snapshot.next_best_action,
            "intent_score": lead.intelligence_snapshot.intent_score,
            "lost_risk_score": None,
        }
    else:
        lead_dict["intelligence_snapshot"] = None

    return {"success": True, "message": "تم تحديث حالة العميل بنجاح", "lead": lead_dict}


@app.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    from services.sse_metrics import compute_and_cache_metrics

    metrics = compute_and_cache_metrics(db, target_cid)
    return {
        **metrics,
        "latest_leads": get_latest_leads(db, target_cid, limit=10),
    }


@app.put("/api/company/target")
def update_company_daily_target(
    request: Request,
    data: CompanyTargetUpdate,
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    company = (
        db.query(Company)
        .filter(
            Company.company_id == target_cid,
            Company.is_deleted == False,
        )
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.daily_sales_target = data.target
    db.commit()

    from services.sse_metrics import invalidate_metrics_cache

    invalidate_metrics_cache(target_cid)
    write_audit_log(
        db,
        "COMPANY_DAILY_TARGET_UPDATE",
        company_id=target_cid,
        ip_address=_get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
        detail=f"daily_sales_target={data.target}",
    )
    return {"success": True, "daily_target": data.target}


@app.get("/leads")
def get_leads_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    result = get_leads_paginated(db, target_cid, page=page, page_size=page_size)

    def contact_identifier_for(lead: Lead):
        channel_type = lead.channel_type or "WHATSAPP_QR"
        if channel_type == "VELOR_WEB_CHAT":
            return lead.external_customer_id
        return (
            lead.whatsapp_number
            or lead.phone
            or lead.whatsapp_jid
            or lead.customer_provided_phone
        )

    return {
        "success": True,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
        "leads": [
            {
                "id": lead.id,
                "name": lead.name,
                "phone": lead.whatsapp_number or lead.phone,
                "channel_type": lead.channel_type or "WHATSAPP_QR",
                "external_customer_id": lead.external_customer_id,
                "contact_identifier": contact_identifier_for(lead),
                "customer_provided_phone": lead.customer_provided_phone,
                "interest": lead.interest,
                "is_paused": lead.is_paused,
                "temperature": lead.temperature,
                "is_hot_deal": lead.is_hot_deal,
                "needs_human_intervention": lead.needs_human_intervention,
                "lead_score": lead.lead_score,
                "status": lead.status,
                "stage": lead.stage,
                "ai_summary": lead.ai_summary,
                "last_message_preview": lead.last_message_preview,
                "last_message": lead.last_message,
                "conversation_count": lead.conversation_count,
                "first_contact_date": _iso_utc(lead.first_contact_date),
                "last_contact_date": _iso_utc(lead.last_contact_date),
                "updated_at": _iso_utc(lead.updated_at),
            }
            for lead in result["items"]
        ],
    }


@app.get("/export-leads")
def export_leads_api(
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    leads = get_leads_paginated(db, target_cid, page=1, page_size=100)["items"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "name",
            "phone",
            "customer_provided_phone",
            "interest",
            "status",
            "stage",
            "lead_score",
            "is_hot_deal",
            "needs_human_intervention",
            "last_contact_date",
        ]
    )
    for lead in leads:
        writer.writerow(
            [
                _sanitize_csv(lead.name),
                _sanitize_csv(lead.whatsapp_number or lead.phone),
                _sanitize_csv(lead.customer_provided_phone),
                _sanitize_csv(lead.interest),
                _sanitize_csv(lead.status),
                _sanitize_csv(lead.stage),
                lead.lead_score,
                lead.is_hot_deal,
                lead.needs_human_intervention,
                _iso_utc(lead.last_contact_date) or "",
            ]
        )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=velor_leads.csv"},
    )


@app.get("/api/conversations")
def get_conversations_api(
    user_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    result = get_conversations_paginated(
        db,
        target_cid,
        user_id=user_id,
        page=page,
        page_size=limit,
    )
    conversations = [
        {
            "id": msg.id,
            "internal_message_id": msg.internal_message_id,
            "wa_message_id": msg.wa_message_id,
            "user_id": msg.user_id,
            "sender": msg.sender,
            "direction": msg.direction,
            "message": msg.message,
            "delivery_status": msg.delivery_status,
            "created_at": _iso_utc(msg.created_at),
            "date": _iso_utc(msg.created_at),
        }
        for msg in result["items"]
    ]
    return {
        "success": True,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
        "conversations": conversations,
    }


def _ensure_v2_channel_lead(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    channel_type: str,
) -> Lead:
    lead = _find_lead_for_user(db, company_id, user_id)
    if lead is not None:
        return lead

    from database import _upsert_usage_in_session

    is_whatsapp = channel_type in {"WHATSAPP_QR", "WHATSAPP_META"}
    normalized = normalize_whatsapp_number(user_id) if is_whatsapp else ""
    lead = Lead(
        company_id=company_id,
        name="عميل محتمل",
        phone=(normalized[:20] if normalized else None),
        whatsapp_number=(normalized[:20] if normalized else None),
        whatsapp_jid=(str(user_id)[:100] if is_whatsapp else None),
        channel_type=channel_type,
        external_customer_id=str(user_id)[:100],
        interest="عام",
        status="new",
        conversation_count=0,
    )
    db.add(lead)
    db.flush()
    _upsert_usage_in_session(db, company_id, leads=1)
    db.add(
        SystemEvent(
            company_id=company_id,
            event_type="lead.created",
            entity_id=str(user_id)[:100],
            payload=json.dumps(
                {
                    "lead_id": lead.id,
                    "channel": channel_type,
                    "source": "v2_conversation_runtime",
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    db.refresh(lead)
    return lead


async def _chat_v2(
    *,
    data: ChatMsg,
    company: Company,
    background_tasks: BackgroundTasks,
    channel_type: str,
    db: Session,
):
    from services.processing_claim import (
        acquire_inbound_processing_claim,
        ClaimResult,
    )
    from services.public_chat_turn_service import (
        cancel_persisted_auto_reply,
        current_auto_reply_block_reason,
        find_reply_for_inbound,
    )
    from services.v2_turn_use_case import execute_v2_turn

    if not data.external_message_id:
        raise HTTPException(
            status_code=400,
            detail="external_message_id is required for reliable V2 message processing",
        )

    lead = _ensure_v2_channel_lead(
        db,
        company_id=company.company_id,
        user_id=data.user_id,
        channel_type=channel_type,
    )

    skip_reason = _auto_reply_skip_reason(db, company, data.user_id)
    if skip_reason:
        claim_result, inbound = acquire_inbound_processing_claim(
            db,
            company.company_id,
            data.user_id,
            data.external_message_id,
            data.message,
            defer_side_effects=False,
            commit=True,
        )
        if claim_result in {ClaimResult.CLAIM_ACQUIRED, ClaimResult.RETRYABLE_RECLAIMED} and inbound:
            _record_auto_reply_skip(
                db,
                company.company_id,
                data.user_id,
                inbound.internal_message_id,
                skip_reason,
            )
            finalize_inbound_processing_claim(
                db,
                inbound.internal_message_id,
                "skipped",
                expected_attempts=inbound.processing_attempts,
            )
        if inbound and claim_result in {
            ClaimResult.CLAIM_ACQUIRED,
            ClaimResult.RETRYABLE_RECLAIMED,
            ClaimResult.INTENTIONALLY_SKIPPED,
        }:
            try:
                from services.workspace_suggestion_service import create_workspace_suggestion_for_message

                create_workspace_suggestion_for_message(
                    db,
                    company.company_id,
                    data.user_id,
                    inbound.internal_message_id,
                    skip_reason,
                )
            except Exception as exc:
                db.rollback()
                log.warning(
                    "Workspace suggested reply generation failed for V2 skipped message %s: %s",
                    inbound.internal_message_id,
                    exc,
                )
        return {
            "reply": None,
            "internal_message_id": inbound.internal_message_id if inbound else None,
            "duplicate": claim_result not in {ClaimResult.CLAIM_ACQUIRED, ClaimResult.RETRYABLE_RECLAIMED},
            "auto_reply_skipped": True,
            "reason": skip_reason,
        }

    monthly_messages, _monthly_leads = get_monthly_usage(db, company.company_id)
    if not check_message_quota(company.plan, monthly_messages):
        claim_result, inbound = acquire_inbound_processing_claim(
            db,
            company.company_id,
            data.user_id,
            data.external_message_id,
            data.message,
            defer_side_effects=False,
            commit=True,
        )
        if claim_result in {ClaimResult.CLAIM_ACQUIRED, ClaimResult.RETRYABLE_RECLAIMED} and inbound:
            _record_auto_reply_skip(
                db,
                company.company_id,
                data.user_id,
                inbound.internal_message_id,
                "quota_exhausted",
            )
            finalize_inbound_processing_claim(
                db,
                inbound.internal_message_id,
                "skipped",
                expected_attempts=inbound.processing_attempts,
            )
        return {
            "reply": "الحساب وصل للحد الشهري للردود الآلية. الرسالة اتسجلت، ويقدر صاحب الحساب يتابعها يدويًا.",
            "internal_message_id": inbound.internal_message_id if inbound else None,
            "quota_exceeded": True,
        }

    claim_result, inbound = acquire_inbound_processing_claim(
        db,
        company.company_id,
        data.user_id,
        data.external_message_id,
        data.message,
        defer_side_effects=True,
        commit=False,
    )
    if claim_result == ClaimResult.ALREADY_PROCESSING:
        return JSONResponse(
            status_code=202,
            content={
                "reply": None,
                "internal_message_id": inbound.internal_message_id if inbound else None,
                "duplicate": True,
                "status": "processing",
            },
        )
    if claim_result == ClaimResult.COMPLETED and inbound is not None:
        reply, response_envelope = find_reply_for_inbound(
            db,
            company_id=company.company_id,
            user_id=data.user_id,
            inbound=inbound,
        )
        if reply is not None:
            delivered = reply.delivery_status in {"sent", "delivered", "read"}
            return {
                "reply": None if delivered and reply.wa_message_id else reply.message,
                "internal_message_id": reply.internal_message_id,
                "duplicate": True,
                "redeliver_existing_reply": not (delivered and reply.wa_message_id),
                "delivery_status": reply.delivery_status,
                **({"response": response_envelope} if response_envelope else {}),
            }
        skipped_reason = _existing_auto_reply_skip_reason(
            db,
            company.company_id,
            inbound.internal_message_id,
        )
        return {
            "reply": None,
            "internal_message_id": inbound.internal_message_id,
            "duplicate": True,
            "auto_reply_skipped": bool(skipped_reason),
            **({"reason": skipped_reason} if skipped_reason else {}),
        }
    if claim_result in {ClaimResult.INTENTIONALLY_SKIPPED, ClaimResult.UNKNOWN_UNSAFE}:
        return {
            "reply": None,
            "internal_message_id": inbound.internal_message_id if inbound else None,
            "duplicate": True,
            "auto_reply_skipped": True,
        }
    if inbound is None:
        raise HTTPException(status_code=409, detail="Unable to establish message processing ownership")

    try:
        timeout_seconds = float(os.getenv("WHATSAPP_REPLY_TIMEOUT_SECONDS", "40"))
    except (TypeError, ValueError):
        timeout_seconds = 40.0
    response_coro = execute_v2_turn(
        db=db,
        company=company,
        lead=lead,
        source_message=inbound,
        company_id=company.company_id,
        lead_id=lead.id,
        user_id=data.user_id,
        customer_text=data.message,
        inbound_internal_id=inbound.internal_message_id,
        processing_claim_attempt=inbound.processing_attempts,
        background_tasks=background_tasks,
        channel_type=channel_type,
        source_route="/chat",
        outbound_delivery_status="pending",
        telemetry_source=(
            "external_api"
            if channel_type == "EXTERNAL_API"
            else "whatsapp_gateway"
        ),
        enforce_auto_reply_guard=True,
    )
    try:
        turn = (
            await asyncio.wait_for(response_coro, timeout=timeout_seconds)
            if timeout_seconds > 0
            else await response_coro
        )
    except Exception:
        db.rollback()
        raise

    trace = turn["trace"]
    result = turn["result"]
    response_envelope = turn.get("response_envelope")
    persisted = turn["persisted"]
    if not persisted:
        return JSONResponse(
            status_code=409,
            content={
                "status": "superseded",
                "reply": None,
                "message": "Message processing was superseded; retry with the same external_message_id",
            },
        )
    if persisted.get("auto_reply_skipped"):
        return {
            "reply": None,
            "internal_message_id": persisted.get("internal_id"),
            "auto_reply_skipped": True,
            "reason": persisted.get("reason"),
        }

    ai_handoff_pause = bool(
        (trace.get("lead_to_save") or {}).get("is_paused") is True
        and (trace.get("conversation_action") or {}).get("type") == "START_HUMAN_HANDOFF"
    )
    late_block_reason = current_auto_reply_block_reason(
        db,
        company_id=company.company_id,
        lead_id=lead.id,
        inbound_internal_id=inbound.internal_message_id,
        allow_ai_handoff_pause=ai_handoff_pause,
    )
    if late_block_reason:
        cancel_persisted_auto_reply(
            db,
            company_id=company.company_id,
            inbound_internal_id=inbound.internal_message_id,
            outbound_internal_id=persisted["internal_id"],
            reason=late_block_reason,
        )
        return {
            "reply": None,
            "internal_message_id": inbound.internal_message_id,
            "auto_reply_skipped": True,
            "reason": late_block_reason,
        }
    return {
        "reply": result["answer_text"],
        "internal_message_id": persisted["internal_id"],
        "delivery_status": "pending",
        **({"response": response_envelope} if response_envelope else {}),
    }


@app.post("/chat")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    data: ChatMsg,
    background_tasks: BackgroundTasks,
    api_key: Optional[str] = Depends(api_key_header),
    internal_secret: Optional[str] = Depends(internal_secret_header),
    gateway_company_id: Optional[str] = Depends(company_id_header),
    db: Session = Depends(get_db),
):
    company = None
    channel_type = "EXTERNAL_API"

    if internal_secret:
        if not _verify_internal_secret(internal_secret):
            raise HTTPException(status_code=401, detail="Unauthorized gateway request")
        company_id = gateway_company_id or request.query_params.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="X-Company-ID is required for gateway chat")
        company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
        channel_type = "WHATSAPP_QR"
    elif api_key:
        company = db.query(Company).filter(Company.api_key_hash == hash_api_key(api_key), Company.is_deleted == False).first()
    else:
        raise HTTPException(status_code=401, detail="Missing API key or internal gateway secret")

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    from services.conversation_engine_config import (
        get_external_api_response_engine,
        get_whatsapp_response_engine,
    )

    selected_engine = (
        get_whatsapp_response_engine()
        if channel_type == "WHATSAPP_QR"
        else get_external_api_response_engine()
    )
    if selected_engine == "v2":
        return await _chat_v2(
            data=data,
            company=company,
            background_tasks=background_tasks,
            channel_type=channel_type,
            db=db,
        )

    existing_incoming = None
    if data.external_message_id:
        existing_incoming = (
            db.query(Message)
            .filter(
                Message.company_id == company.company_id,
                Message.wa_message_id == data.external_message_id,
                Message.direction == "incoming",
            )
            .first()
        )
        if existing_incoming:
            existing_reply = (
                db.query(Message)
                .filter(
                    Message.company_id == company.company_id,
                    Message.user_id == existing_incoming.user_id,
                    Message.direction == "outgoing",
                    Message.sender == "assistant",
                    Message.id > existing_incoming.id,
                )
                .order_by(Message.id.asc())
                .first()
            )
            if existing_reply:
                delivered_statuses = {"sent", "delivered", "read"}
                if existing_reply.delivery_status in delivered_statuses and existing_reply.wa_message_id:
                    return {"reply": None, "internal_message_id": existing_reply.internal_message_id, "duplicate": True}

                return {
                    "reply": existing_reply.message,
                    "internal_message_id": existing_reply.internal_message_id,
                    "duplicate": True,
                    "redeliver_existing_reply": True,
                    "delivery_status": existing_reply.delivery_status,
                }

            skipped_reason = _existing_auto_reply_skip_reason(db, company.company_id, existing_incoming.internal_message_id)
            if skipped_reason:
                return {
                    "reply": None,
                    "internal_message_id": existing_incoming.internal_message_id,
                    "duplicate": True,
                    "auto_reply_skipped": True,
                    "reason": skipped_reason,
                }

            return {"reply": None, "internal_message_id": existing_incoming.internal_message_id, "duplicate": True}

    skip_reason = _auto_reply_skip_reason(db, company, data.user_id)
    if skip_reason:
        internal_id = _persist_skipped_auto_reply_inbound(
            db,
            company.company_id,
            data.user_id,
            data.message,
            data.external_message_id,
            skip_reason,
        )
        return {
            "reply": None,
            "internal_message_id": internal_id,
            "auto_reply_skipped": True,
            "reason": skip_reason,
        }

    monthly_messages, _monthly_leads = get_monthly_usage(db, company.company_id)
    if not check_message_quota(company.plan, monthly_messages):
        return {
            "reply": "تم الوصول للحد الشهري من الرسائل. يرجى ترقية الباقة لاستكمال الردود الآلية.",
            "internal_message_id": None,
            "quota_exceeded": True,
        }

    reply, internal_id = await get_ai_response(
        db=db,
        user_input=data.message,
        user_id=data.user_id,
        company_id=company.company_id,
        background_tasks=background_tasks,
        incoming_wa_message_id=data.external_message_id,
        persist_incoming=existing_incoming is None,
    )

    return {"reply": reply, "internal_message_id": internal_id}


@app.post("/api/ai/suggestions")
@limiter.limit("10/minute")
async def get_ai_suggestions(
    request: Request, data: AISuggestionRequest, db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)
):

    suggestions = []

    if data.is_first_takeover:
        suggestions.append(f"أهلاً بك يا {data.client_name}، تم إيقاف المساعد الذكي والآن معك ممثل خدمة العملاء لمساعدتك 🫡")

    system_prompt = """You are an expert, professional customer service agent assistant.
Your task is to generate exactly 2 short, highly professional, and context-aware responses in Arabic based strictly on the provided chat history.
DO NOT hallucinate offers, prices, or information not explicitly mentioned in the history.
Respond strictly in valid JSON format: {"suggestions": ["reply1", "reply2"]}"""

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Chat history:\n{chr(10).join(data.chat_history)}\n\nProvide 2 suggestions."},
        ]
        response = await asyncio.wait_for(
            groq_client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=messages,
                temperature=0.7,
                max_tokens=int(os.getenv("GROQ_MAX_TOKENS", 300)),
                response_format={"type": "json_object"},
            ),
            timeout=15.0,
        )

        raw_content = response.choices[0].message.content.strip()
        result = json.loads(raw_content)
        ai_suggestions = result.get("suggestions", [])

        # Ensure we only append up to 2 AI suggestions
        if isinstance(ai_suggestions, list):
            suggestions.extend([str(s) for s in ai_suggestions[:2]])

    except Exception as e:
        log.error("AI Suggestions generation failed: %s", e)
        # Fallback if generation fails and list is empty
        if not suggestions:
            suggestions.append("كيف يمكنني مساعدتك اليوم؟")

    return {"suggestions": suggestions}


def _lead_priority_payload(lead: Lead) -> dict:
    snapshot = getattr(lead, "intelligence_snapshot", None)
    priority_score = snapshot.priority_score if snapshot else max(lead.lead_score or 0, int(lead.intent_score or 0))
    why_summary = (snapshot.why_summary if snapshot else None) or lead.ai_summary or lead.summary or lead.last_message_preview or ""
    next_best_action = (snapshot.next_best_action if snapshot else None) or "راجع المحادثة وحدد الخطوة التالية مع العميل."
    return {
        "lead_id": lead.id,
        "name": lead.name,
        "phone": lead.whatsapp_number or lead.phone,
        "stage": lead.stage,
        "status": lead.status,
        "priority_score": int(priority_score or 0),
        "lead_score": lead.lead_score or 0,
        "intent_score": lead.intent_score or 0,
        "next_best_action": next_best_action,
        "why_summary": why_summary,
        "last_contact": _iso_utc(lead.last_contact_date),
    }


@app.get("/api/engine/priorities")
def engine_priorities(
    limit: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    from services.priority_actions_service import get_priority_actions

    return get_priority_actions(db, target_cid, limit=limit)


@app.get("/api/engine/attention")
def engine_attention(
    limit: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id),
):
    from services.owner_attention_projection_service import get_owner_attention_projection

    return get_owner_attention_projection(db, target_cid, limit=limit)


@app.get("/api/engine/queue")
def engine_queue(db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    from services.follow_up_service import list_follow_ups, serialize_follow_up

    tasks = list_follow_ups(db, target_cid, statuses={"pending", "snoozed"}, limit=100)
    return {
        "success": True,
        "deprecated": True,
        "tasks": [serialize_follow_up(task) for task in tasks],
    }


@app.get("/api/engine/lost")
def engine_lost(db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    from services.owner_attention_projection_service import get_commercial_queue

    queue = get_commercial_queue(db, target_cid, limit=100).get("items", [])
    return {
        "success": True,
        "deprecated": True,
        "lost_candidates": [item for item in queue if item.get("category") == "AT_RISK"],
    }


@app.get("/api/engine/opportunity")
def engine_opportunity(db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    from services.owner_attention_projection_service import get_commercial_queue

    queue = get_commercial_queue(db, target_cid, limit=100).get("items", [])
    return {
        "success": True,
        "deprecated": True,
        "money_left_on_table": None,
        "recovered_revenue": None,
        "attributed_revenue": None,
        "financial_outcomes": {
            "status": "not_connected",
            "reason": "No authoritative order or payment provider is connected.",
        },
        "leads_at_risk_count": len([item for item in queue if item.get("category") == "AT_RISK"]),
        "high_value_opportunities_count": None,
        "at_risk_deals": [item for item in queue if item.get("category") == "AT_RISK"],
        "opportunities": queue,
    }


@app.post("/api/engine/tasks/{task_id}/complete")
def complete_engine_task(task_id: int, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    from services.follow_up_service import transition_follow_up

    task = transition_follow_up(db, company_id=target_cid, task_id=task_id, target_status="completed")
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True}


@app.post("/api/engine/tasks/{task_id}/dismiss")
def dismiss_engine_task(task_id: int, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    from services.follow_up_service import transition_follow_up

    task = transition_follow_up(db, company_id=target_cid, task_id=task_id, target_status="dismissed")
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True}


class EngineOverrideRequest(BaseModel):
    lead_id: int
    stage: Optional[str] = None
    opportunity_value: Optional[float] = None


@app.post("/api/engine/override")
def engine_override(req: EngineOverrideRequest, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    lead = db.query(Lead).filter(Lead.id == req.lead_id, Lead.company_id == target_cid, Lead.is_deleted == False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if req.stage:
        lead.stage = req.stage
        lead.stage_updated_at = datetime.now(timezone.utc)
    if req.opportunity_value is not None:
        raise HTTPException(
            status_code=422,
            detail="Unverified opportunity values are not accepted by the commercial authority contract.",
        )
    db.commit()
    return {"success": True}


@app.get("/api/notifications")
def get_notifications(db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    notifs = db.query(Notification).filter(Notification.company_id == target_cid).order_by(Notification.created_at.desc()).limit(50).all()
    return {
        "success": True,
        "notifications": [
            {
                "id": n.id,
                "lead_id": n.lead_id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "created_at": _iso_utc(n.created_at),
                "read": n.read_at is not None,
            }
            for n in notifs
        ],
    }


@app.post("/api/notifications/{n_id}/read")
def read_notification(n_id: int, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    n = db.query(Notification).filter(Notification.id == n_id, Notification.company_id == target_cid).first()
    if n and not n.read_at:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"success": True}


@app.post("/api/notifications/read-all")
def read_all_notifications(db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    now = datetime.now(timezone.utc)
    db.query(Notification).filter(Notification.company_id == target_cid, Notification.read_at.is_(None)).update({"read_at": now})
    db.commit()
    return {"success": True}


@app.get("/stream-stats")
async def stream_stats(request: Request, target_cid: str = Depends(_resolve_company_id)):
    async def event_generator():
        from services.sse_metrics import compute_and_cache_metrics

        last_yielded_dt = None
        has_yielded_initial_stats = False
        last_err = None

        while True:
            if await request.is_disconnected():
                break

            try:
                # Offload all DB-heavy work to a thread to keep the async loop responsive
                def poll_db():
                    try:
                        with SessionLocal() as db:
                            # Determine updated leads since last tick
                            if not has_yielded_initial_stats:
                                updated_leads = (
                                    db.query(Lead)
                                    .filter(Lead.company_id == target_cid, Lead.is_deleted == False)
                                    .order_by(Lead.updated_at.desc())
                                    .limit(1)
                                    .all()
                                )
                            else:
                                if last_yielded_dt:
                                    updated_leads = (
                                        db.query(Lead)
                                        .filter(Lead.company_id == target_cid, Lead.is_deleted == False, Lead.updated_at > last_yielded_dt)
                                        .order_by(Lead.updated_at.asc())
                                        .all()
                                    )
                                else:
                                    updated_leads = []

                            latest_leads_payload = []
                            current_max_dt = last_yielded_dt

                            from sqlalchemy import func

                            m_counts_by_phone = {}
                            if updated_leads:
                                all_variants = []
                                for l in updated_leads:
                                    all_variants.extend(get_phone_variants(normalize_whatsapp_number(l.phone or "")))

                                if all_variants:
                                    counts = (
                                        db.query(Message.user_id, func.count(Message.id))
                                        .filter(Message.company_id == target_cid, Message.user_id.in_(all_variants))
                                        .group_by(Message.user_id)
                                        .all()
                                    )
                                    m_counts_by_phone = {uid: c for uid, c in counts}

                            for existing_lead in updated_leads:
                                # lightweight refresh
                                db.refresh(existing_lead)
                                base_phone = normalize_whatsapp_number(existing_lead.phone or "")
                                m_count = sum(m_counts_by_phone.get(v, 0) for v in get_phone_variants(base_phone))
                                replies_key = (target_cid, existing_lead.whatsapp_number or existing_lead.phone)
                                qr = latest_quick_replies.get(replies_key, [])

                                payload = {
                                    "phone": existing_lead.whatsapp_number or existing_lead.phone,
                                    "customer_provided_phone": existing_lead.customer_provided_phone,
                                    "name": existing_lead.name,
                                    "interest": existing_lead.interest,
                                    "messages_count": m_count,
                                    "is_paused": existing_lead.is_paused,
                                    "temperature": existing_lead.temperature,
                                    "is_hot_deal": existing_lead.is_hot_deal,
                                    "needs_human_intervention": existing_lead.needs_human_intervention,
                                    "lead_score": existing_lead.lead_score,
                                    "status": existing_lead.status,
                                    "stage": existing_lead.stage,
                                    "intelligence_snapshot": (
                                        {
                                            "why_summary": (
                                                existing_lead.intelligence_snapshot.why_summary if existing_lead.intelligence_snapshot else ""
                                            ),
                                            "next_best_action": (
                                                existing_lead.intelligence_snapshot.next_best_action if existing_lead.intelligence_snapshot else ""
                                            ),
                                            "intent_score": (
                                                existing_lead.intelligence_snapshot.intent_score if existing_lead.intelligence_snapshot else 0
                                            ),
                                            "lost_risk_score": None,
                                        }
                                        if existing_lead.intelligence_snapshot
                                        else None
                                    ),
                                    "ai_summary": existing_lead.ai_summary,
                                    "last_message_preview": existing_lead.last_message_preview,
                                    "last_message": existing_lead.last_message,
                                    "last_message_sender": existing_lead.last_message_sender,
                                    "conversation_count": existing_lead.conversation_count,
                                    "first_contact_date": _iso_utc(existing_lead.first_contact_date),
                                    "last_contact_date": _iso_utc(existing_lead.last_contact_date),
                                    "quick_replies": qr,
                                    "_ts": existing_lead.updated_at.strftime("%I:%M %p") if existing_lead.updated_at else "",
                                }
                                latest_leads_payload.append(payload)

                                if existing_lead.updated_at and (not current_max_dt or existing_lead.updated_at > current_max_dt):
                                    current_max_dt = existing_lead.updated_at

                            # Heavy metrics: compute in-thread (uses DB) and return together
                            metrics = compute_and_cache_metrics(db, target_cid)

                            return {
                                "metrics": metrics,
                                "latest_leads": latest_leads_payload,
                                "current_max_dt": current_max_dt,
                            }
                    except Exception:
                        raise

                # Avoid spawning unlimited DB workers: acquire semaphore non-blocking
                if await request.is_disconnected():
                    break

                acquired = _DB_WORKER_SEM.acquire(blocking=False)
                if not acquired:
                    # Semaphore saturated; skip this tick to avoid threadpool/DB exhaustion
                    await asyncio.sleep(2)
                    continue

                try:
                    # Double-check client still connected before heavy work
                    if await request.is_disconnected():
                        break

                    result = await anyio.to_thread.run_sync(poll_db)

                    if result:
                        data = {**result["metrics"], "latest_leads": result["latest_leads"]}
                        if data:
                            log.debug("Broadcasting SSE stats for %s", target_cid)
                            yield f"data: {json.dumps(data)}\n\n"
                            last_yielded_dt = result["current_max_dt"]
                            has_yielded_initial_stats = True
                finally:
                    try:
                        _DB_WORKER_SEM.release()
                    except Exception:
                        # release best-effort
                        pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                error_msg = str(e)
                if error_msg != last_err:
                    log.error("SSE stream error: %s", error_msg)
                    last_err = error_msg

            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── WhatsApp Gateway Proxy ─────────────────────────────────────────────


@app.get("/api/internal/companies/{company_id}/exists")
async def internal_company_exists(
    company_id: str,
    db: Session = Depends(get_db),
    internal_secret: Optional[str] = Depends(internal_secret_header),
):
    if not _verify_internal_secret(internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized gateway request")
    if not re.match(r"^[\w-]{1,64}$", company_id):
        raise HTTPException(status_code=400, detail="Invalid company_id")

    exists = (
        db.query(Company.id)
        .filter(
            Company.company_id == company_id,
            Company.is_deleted == False,
        )
        .first()
        is not None
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"success": True, "exists": True, "company_id": company_id}


@app.post("/api/whatsapp/webhook/ack")
async def whatsapp_webhook_ack(
    payload: AckPayload,
    db: Session = Depends(get_db),
    internal_secret: Optional[str] = Depends(internal_secret_header),
):
    if not _verify_internal_secret(internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized gateway request")

    # Try to find message by internal ID first, then wa_message_id
    msg = None
    if payload.internal_message_id:
        query = db.query(Message).filter(Message.internal_message_id == payload.internal_message_id)
        if payload.company_id:
            query = query.filter(Message.company_id == payload.company_id)
        msg = query.first()
    if not msg and payload.wa_message_id:
        query = db.query(Message).filter(Message.wa_message_id == payload.wa_message_id)
        if payload.company_id:
            query = query.filter(Message.company_id == payload.company_id)
        msg = query.first()

    if not msg:
        return {"success": False, "detail": "Message not found"}

    result = apply_message_delivery_update(
        db,
        msg,
        payload.status,
        provider_message_id=payload.wa_message_id,
        event_timestamp=payload.timestamp,
    )
    if not result.status_changed:
        return {
            "success": True,
            "detail": "Ignored invalid or duplicate state transition",
        }
    return {"success": True}


@app.get("/api/whatsapp/pending/{company_id}")
async def get_whatsapp_pending(company_id: str, db: Session = Depends(get_db), current_user: dict = Depends(_get_current_user)):

    # Ignore company_id from URL completely to prevent cross-company access.
    # Enforce resolution from authenticated user context.
    # If super_admin is accessing, they would typically use a query param, but
    # to keep this strict and prevent bypass via path, we strictly use their token's company_id
    # or handle super_admin explicitly if needed. For safety, we use current_user["company_id"].

    safe_company_id = current_user["company_id"]
    if current_user["role"] == "super_admin":
        # Super admins can optionally read the path parameter if we want to allow them
        safe_company_id = company_id

    # We only want to recover OUTGOING messages that are stuck in 'pending'
    pending = (
        db.query(Message)
        .filter(Message.company_id == safe_company_id, Message.direction == "outgoing", Message.delivery_status == "pending")
        .order_by(Message.created_at.asc())
        .all()
    )

    return {
        "success": True,
        "pending": [
            {
                "internal_message_id": m.internal_message_id,
                "phone": m.user_id,
                "message": m.message,
                "created_at": _iso_utc(m.created_at),
            }
            for m in pending
        ],
    }


@app.post("/whatsapp/start")
@limiter.limit("5/minute")
async def whatsapp_start(
    request: Request,
    target_cid: str = Depends(_resolve_company_id),
):
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{NODE_GATEWAY_URL}/api/whatsapp/start/{target_cid}",
                headers=_node_headers(),
            )
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except HTTPException:
        raise
    except Exception as exc:
        log.error("WhatsApp start proxy error: %s", exc)
        raise HTTPException(status_code=502, detail="WhatsApp gateway unavailable")


@app.get("/whatsapp/status")
async def whatsapp_status(target_cid: str = Depends(_resolve_company_id)):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{NODE_GATEWAY_URL}/api/whatsapp/status/{target_cid}",
                headers=_node_headers(),
            )
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except HTTPException:
        raise
    except Exception as exc:
        log.error("WhatsApp status proxy error: %s", exc)
        raise HTTPException(status_code=502, detail="WhatsApp gateway unavailable")


@app.get("/whatsapp/stream")
async def whatsapp_stream(
    request: Request,
    target_cid: str = Depends(_resolve_company_id),
):
    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET",
                    f"{NODE_GATEWAY_URL}/api/whatsapp/stream/{target_cid}",
                    headers=_node_headers(),
                ) as resp:
                    if resp.status_code != 200:
                        yield 'data: {"status":"gateway_error","qr":null}\n\n'
                        return

                    async for line in resp.aiter_lines():
                        if await request.is_disconnected():
                            break
                        # Preserve SSE format: data lines need \n\n terminator
                        if line.startswith("data:"):
                            yield f"{line}\n\n"
                        elif line.startswith(":"):
                            # SSE comment (e.g. ": ping") — forward as keepalive
                            yield f"{line}\n"
                        elif line.strip():
                            # Any other non-empty line — forward with newline
                            yield f"{line}\n"
        except Exception as exc:
            # Log error and also yield a machine-readable SSE error event so clients can show diagnostics
            log.exception("WhatsApp stream proxy error while proxying gateway stream for %s", target_cid)
            try:
                yield f'data: {json.dumps({"status": "error", "message": "WhatsApp gateway stream error"})}\n\n'
            except Exception:
                # best-effort only
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/whatsapp/leads/latest")
def get_latest_leads_api(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: dict = Depends(_get_current_user),
):
    leads = get_latest_leads(db, current_user["company_id"], limit)
    return {"success": True, "leads": leads}


@app.get("/api/leads/{lead_id}/timeline")
def get_lead_timeline(lead_id: int, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):

    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == target_cid).first()
    if not lead:
        raise HTTPException(404, "Lead not found")

    timeline = []

    # 1. Lead creation
    if lead.created_at:
        timeline.append(
            {
                "timestamp": _iso_utc(lead.created_at),
                "type": "lead_created",
                "title": "تم إضافة العميل",
                "description": f"تم تسجيل العميل في النظام ({lead.interest or 'بدون اهتمام محدد'})",
                "source": "system",
            }
        )

    # 2. Lead Events (Primary Business Events)
    events = db.query(LeadEvent).filter(LeadEvent.lead_id == lead_id).all()
    for evt in events:
        # Determine source based on some basic heuristics, default to analyzer
        source = "analyzer"
        # The AI usually outputs descriptive event types.
        timeline.append(
            {
                "timestamp": _iso_utc(evt.timestamp),
                "type": "lead_event",
                "title": evt.event_type,
                "description": evt.description,
                "source": source,
            }
        )

    # 3. FollowUpTasks
    tasks = db.query(FollowUpTask).filter(FollowUpTask.lead_id == lead_id).all()
    for task in tasks:
        timeline.append(
            {
                "timestamp": _iso_utc(task.created_at),
                "type": "follow_up_creation",
                "title": "تم إنشاء متابعة",
                "description": f"متابعة مجدولة: {task.task_type}" + (f" (الحالة: {task.status})" if task.status else ""),
                "source": "followup_engine",
            }
        )

    # 4. LeadSignals (Metadata)
    signals = db.query(LeadSignal).filter(LeadSignal.lead_id == lead_id).all()
    for sig in signals:
        timeline.append(
            {
                "timestamp": _iso_utc(sig.timestamp),
                "type": "signal",
                "title": f"إشارة: {sig.signal_category}",
                "description": f"{sig.reasoning} (تأثير: {sig.score_modifier})",
                "source": "scoring_engine",
            }
        )

    # Filter out missing timestamps, then sort oldest to newest
    timeline = [t for t in timeline if t["timestamp"]]
    timeline.sort(key=lambda x: x["timestamp"])

    return {"success": True, "timeline": timeline}


@app.get("/api/leads/{lead_id}/memory")
def get_lead_memory(lead_id: int, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == target_cid).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    memory = db.query(LeadMemory).filter(LeadMemory.lead_id == lead_id).first()
    if not memory:
        return {"success": True, "memory": None}

    def parse_json(val):
        if not val:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    return {
        "success": True,
        "memory": {
            "customer_summary": parse_json(memory.customer_summary),
            "product_interest": parse_json(memory.product_interest),
            "budget": parse_json(memory.budget),
            "preferences": parse_json(memory.preferences),
            "purchase_history": parse_json(memory.purchase_history),
            "last_updated": _iso_utc(memory.last_updated),
            "last_memory_rebuild_at": _iso_utc(memory.last_memory_rebuild_at),
        },
    }


@app.post("/api/leads/{lead_id}/memory/rebuild")
def rebuild_lead_memory_endpoint(
    lead_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), target_cid: str = Depends(_resolve_company_id)
):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == target_cid).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    from engine.memory import rebuild_lead_memory_task

    # Note: user_id is passed as phone. brain.py usually converts phone back to JID or just uses it.
    background_tasks.add_task(rebuild_lead_memory_task, target_cid, lead.phone, lead.id)

    return {"success": True, "message": "Memory rebuild triggered"}


class TogglePauseRequest(BaseModel):
    phone: str


def _apply_human_takeover(
    db: Session,
    company_id: str,
    lead: Lead,
    enabled: bool,
    *,
    source: str,
) -> None:
    """Apply the single takeover contract used by inbox and workspace."""
    entering_takeover = bool(enabled and not lead.is_paused)
    lead.is_paused = bool(enabled)
    if entering_takeover and source != "manual_send":
        from services.workspace_suggestion_service import invalidate_lead_suggestions

        invalidate_lead_suggestions(db, company_id, lead.id, "human_takeover")
    db.commit()

    if entering_takeover:
        try:
            from services.pilot_telemetry_service import record_pilot_event

            record_pilot_event(
                db,
                event_name="owner_takeover",
                company_id=company_id,
                actor_type="owner",
                entity_id=lead.id,
                source=source,
            )
        except Exception as exc:
            db.rollback()
            log.warning("Owner takeover telemetry failed category=%s", exc.__class__.__name__)


def _assert_draft_source_is_current(
    db: Session,
    *,
    company_id: str,
    lead: Lead,
    source_message_internal_id: Optional[str],
) -> None:
    """Reject a suggestion-derived send unless its customer turn is current.

    This is intentionally optional: owner-authored manual messages keep the
    existing API contract. When a source version is supplied, however, the
    server—not SSE timing in the browser—is the final authority.
    """
    if not source_message_internal_id:
        return

    user_ids = set()
    for value in (
        lead.external_customer_id,
        lead.whatsapp_jid,
        lead.customer_provided_phone,
        lead.phone,
        lead.whatsapp_number,
    ):
        if not value:
            continue
        text = str(value)
        user_ids.add(text)
        normalized = normalize_whatsapp_number(text)
        if normalized:
            user_ids.add(normalized)
            user_ids.update(get_phone_variants(normalized))

    source = (
        db.query(Message)
        .filter(
            Message.company_id == company_id,
            Message.user_id.in_(user_ids),
            Message.internal_message_id == source_message_internal_id,
            Message.direction == "incoming",
            Message.sender.in_(("user", "customer")),
        )
        .first()
        if user_ids
        else None
    )
    latest = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.user_id.in_(user_ids))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
        if user_ids
        else None
    )
    if source is None or latest is None or latest.id != source.id:
        raise HTTPException(
            status_code=409,
            detail="The suggested reply is stale because the conversation has advanced.",
        )


def _validate_suggestion_send(
    db: Session,
    *,
    company_id: str,
    lead: Lead,
    message_text: str,
    suggestion_id: Optional[int],
    variant_style: Optional[str],
    source_message_internal_id: Optional[str],
):
    """Return the verified suggestion and server-computed edit status."""
    from database import WorkspaceSuggestedReply

    if suggestion_id is None:
        if variant_style:
            raise HTTPException(status_code=400, detail="suggestion_id is required for suggestion metadata")
        _assert_draft_source_is_current(
            db,
            company_id=company_id,
            lead=lead,
            source_message_internal_id=source_message_internal_id,
        )
        return None, None
    if not source_message_internal_id or not variant_style:
        raise HTTPException(status_code=400, detail="Suggestion source and variant are required")

    suggestion = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.id == suggestion_id,
        WorkspaceSuggestedReply.company_id == company_id,
        WorkspaceSuggestedReply.lead_id == lead.id,
        WorkspaceSuggestedReply.status == "suggested",
    ).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Active suggested reply not found")
    if suggestion.source_message_internal_id != source_message_internal_id:
        raise HTTPException(status_code=409, detail="Suggested reply source does not match")

    try:
        variants = json.loads(suggestion.variants_json or "[]")
    except (TypeError, json.JSONDecodeError):
        variants = []
    if not variants:
        variants = [{"style": suggestion.style or "natural", "text": suggestion.suggested_reply}]
    selected = next(
        (
            item for item in variants
            if isinstance(item, dict) and str(item.get("style") or "") == variant_style and isinstance(item.get("text"), str)
        ),
        None,
    )
    if not selected:
        raise HTTPException(status_code=409, detail="Suggested reply variant is no longer available")

    try:
        _assert_draft_source_is_current(
            db,
            company_id=company_id,
            lead=lead,
            source_message_internal_id=source_message_internal_id,
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            suggestion.status = "stale"
            suggestion.stale_reason = "conversation_advanced"
            try:
                from services.pilot_telemetry_service import record_pilot_event

                record_pilot_event(
                    db,
                    event_name="suggestion_stale_blocked",
                    company_id=company_id,
                    actor_type="owner",
                    entity_id=suggestion.id,
                    source="outbound_validation",
                    idempotency_key=f"suggestion:{suggestion.id}:stale-blocked",
                    metadata={
                        "lead_id": lead.id,
                        "suggestion_id": suggestion.id,
                        "variant_style": variant_style,
                        "source_message_internal_id": source_message_internal_id,
                    },
                    commit=False,
                )
                db.commit()
            except Exception as telemetry_exc:
                db.rollback()
                log.warning("Suggestion stale telemetry failed category=%s", telemetry_exc.__class__.__name__)
        raise
    edited = message_text.strip() != selected["text"].strip()
    return suggestion, edited


def _finalize_verified_owner_send(
    db: Session,
    *,
    company_id: str,
    lead: Lead,
    internal_message_id: str,
    source_message_internal_id: Optional[str],
    suggestion,
    variant_style: Optional[str],
    suggestion_edited: Optional[bool],
) -> None:
    outbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.internal_message_id == internal_message_id,
    ).first()
    if not outbound:
        return
    source = None
    if source_message_internal_id:
        source = db.query(Message).filter(
            Message.company_id == company_id,
            Message.internal_message_id == source_message_internal_id,
            Message.direction == "incoming",
        ).first()
        if source:
            outbound.in_reply_to_message_id = source.id

    from services.follow_up_service import complete_reply_required_tasks

    complete_reply_required_tasks(
        db,
        company_id=company_id,
        lead=lead,
        outbound_message=outbound,
        source_message_internal_id=source_message_internal_id,
        commit=False,
    )
    if suggestion is not None:
        suggestion.status = "used"
        from services.pilot_telemetry_service import record_pilot_event

        record_pilot_event(
            db,
            event_name="suggestion_sent",
            company_id=company_id,
            actor_type="owner",
            entity_id=suggestion.id,
            source="outbound_success",
            idempotency_key=f"suggestion:{suggestion.id}:sent:{internal_message_id}",
            metadata={
                "lead_id": lead.id,
                "suggestion_id": suggestion.id,
                "variant_style": variant_style,
                "edited": bool(suggestion_edited),
                "source_message_internal_id": source_message_internal_id,
            },
            commit=False,
        )
    db.commit()


async def dispatch_outbound_message(
    target_cid: str,
    phone_or_visitor_id: str,
    message_text: str,
    background_tasks: BackgroundTasks,
    db: Session,
    source_message_internal_id: Optional[str] = None,
    suggestion_id: Optional[int] = None,
    variant_style: Optional[str] = None,
    suggestion_edited: Optional[bool] = None,
):
    wa_num = normalize_whatsapp_number(phone_or_visitor_id)
    lead = db.query(Lead).filter(
        Lead.company_id == target_cid,
        (Lead.whatsapp_number == wa_num) | (Lead.phone == phone_or_visitor_id) | (Lead.external_customer_id == phone_or_visitor_id)
    ).first()
    if not lead:
        raise HTTPException(404, "Lead not found")

    suggestion, verified_edited = _validate_suggestion_send(
        db,
        company_id=target_cid,
        lead=lead,
        message_text=message_text,
        suggestion_id=suggestion_id,
        variant_style=variant_style,
        source_message_internal_id=source_message_internal_id,
    )
    _apply_human_takeover(db, target_cid, lead, True, source="manual_send")

    def response_message(internal_id: str, delivery_status: str) -> dict:
        persisted = (
            db.query(Message)
            .filter(
                Message.company_id == target_cid,
                Message.internal_message_id == internal_id,
            )
            .first()
        )
        return {
            "type": "message",
            "id": persisted.id if persisted else None,
            "internal_message_id": internal_id,
            "sender": "owner",
            "direction": "outgoing",
            "source": "workspace_manual",
            "is_ai": False,
            "message": message_text,
            "delivery_status": delivery_status,
            "status": delivery_status,
            "timestamp": _iso_utc(persisted.created_at) if persisted else _iso_utc(datetime.now(timezone.utc)),
        }

    if lead.channel_type == "VELOR_WEB_CHAT":
        suggestion, verified_edited = _validate_suggestion_send(
            db,
            company_id=target_cid,
            lead=lead,
            message_text=message_text,
            suggestion_id=suggestion_id,
            variant_style=variant_style,
            source_message_internal_id=source_message_internal_id,
        )
        internal_id = str(uuid.uuid4())
        save_message(
            db,
            target_cid,
            lead.external_customer_id,
            "owner",
            message_text,
            internal_id,
            "outgoing",
            delivery_status="sent"
        )
        msg = db.query(Message).filter(Message.internal_message_id == internal_id).first()
        if msg:
            db.add(MessageEvent(message_id=msg.id, status="sent"))
            db.commit()
        _finalize_verified_owner_send(
            db,
            company_id=target_cid,
            lead=lead,
            internal_message_id=internal_id,
            source_message_internal_id=source_message_internal_id,
            suggestion=suggestion,
            variant_style=variant_style,
            suggestion_edited=verified_edited,
        )
            
        background_tasks.add_task(summarize_conversation, target_cid, lead.external_customer_id)
        return {
            "success": True,
            "status": "Message Sent",
            "message": response_message(internal_id, "sent"),
            "internal_message_id": internal_id,
        }

    # Resolve the WhatsApp JID from existing conversation or phone number
    clean_phone = re.sub(r"\D", "", phone_or_visitor_id or "")
    base_phone = (
        clean_phone[2:]
        if clean_phone.startswith("201") and len(clean_phone) >= 12
        else (clean_phone[1:] if clean_phone.startswith("01") and len(clean_phone) >= 11 else clean_phone)
    )
    conv = (
        db.query(Message)
        .filter(Message.company_id == target_cid, Message.user_id.in_(get_phone_variants(base_phone)))
        .order_by(Message.created_at.desc())
        .first()
    )

    def _is_whatsapp_jid(value: str) -> bool:
        return bool(value and (value.endswith("@s.whatsapp.net") or value.endswith("@lid") or value.endswith("@g.us")))

    if conv:
        real_jid = conv.user_id
        if real_jid and not _is_whatsapp_jid(real_jid):
            real_jid = f"{real_jid}@s.whatsapp.net"
    elif lead.whatsapp_jid:
        real_jid = lead.whatsapp_jid
    else:
        clean_phone = phone_or_visitor_id.replace("+", "").strip()
        if clean_phone.startswith("01") and len(clean_phone) == 11:
            real_jid = f"20{clean_phone[1:]}@s.whatsapp.net"
        else:
            real_jid = f"{clean_phone}@s.whatsapp.net"

    # Derive the user_id that matches how messages are stored
    user_id_for_save = conv.user_id if conv else (lead.whatsapp_jid or real_jid)

    suggestion, verified_edited = _validate_suggestion_send(
        db,
        company_id=target_cid,
        lead=lead,
        message_text=message_text,
        suggestion_id=suggestion_id,
        variant_style=variant_style,
        source_message_internal_id=source_message_internal_id,
    )
    internal_id = str(uuid.uuid4())
    save_message(db, target_cid, user_id_for_save, "owner", message_text, internal_id, "outgoing", delivery_status="pending")

    def mark_takeover_failed() -> None:
        msg = (
            db.query(Message)
            .filter(
                Message.company_id == target_cid,
                Message.internal_message_id == internal_id,
            )
            .first()
        )
        if msg:
            msg.delivery_status = "failed"
            db.add(MessageEvent(message_id=msg.id, status="failed", timestamp=datetime.now(timezone.utc)))
            db.commit()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{NODE_GATEWAY_URL}/whatsapp/agent/takeover",
                json={
                    "company_id": target_cid,
                    "phone": phone_or_visitor_id,
                    "message": message_text,
                    "jid": real_jid,
                    "internal_message_id": internal_id,
                },
                headers=_node_headers(),
            )
            resp.raise_for_status()

    except httpx.HTTPStatusError as exc:
        err_body = exc.response.text
        log.error("Gateway HTTP error [%s]: %s", exc.response.status_code, err_body)
        mark_takeover_failed()
        try:
            err_msg = exc.response.json().get("message", err_body)
        except Exception:
            err_msg = err_body
        raise HTTPException(exc.response.status_code, f"Failed to send: {err_msg}")

    except httpx.RequestError as exc:
        log.error("Gateway connection/request error: %s", exc)
        mark_takeover_failed()
        raise HTTPException(502, f"Failed to connect to WhatsApp Gateway: {str(exc)}")

    except Exception as e:
        log.error("Failed to forward takeover message: %s", str(e))
        mark_takeover_failed()
        raise HTTPException(500, f"Internal server error: {str(e)}")

    # Success path — save message with delivered status
    _finalize_verified_owner_send(
        db,
        company_id=target_cid,
        lead=lead,
        internal_message_id=internal_id,
        source_message_internal_id=source_message_internal_id,
        suggestion=suggestion,
        variant_style=variant_style,
        suggestion_edited=verified_edited,
    )
    background_tasks.add_task(summarize_conversation, target_cid, user_id_for_save)

    return {
        "success": True,
        "status": "Message Sent",
        "message": response_message(internal_id, "pending"),
        "internal_message_id": internal_id,
    }


@app.post("/api/agent/outbound/send")
async def agent_outbound_send(
    req: TakeoverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id)
):
    return await dispatch_outbound_message(
        target_cid,
        req.phone,
        req.message,
        background_tasks,
        db,
        source_message_internal_id=req.source_message_internal_id,
        suggestion_id=req.suggestion_id,
        variant_style=req.variant_style,
        suggestion_edited=req.suggestion_edited,
    )


@app.post("/whatsapp/agent/takeover")
async def agent_takeover(
    req: TakeoverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    target_cid: str = Depends(_resolve_company_id)
):
    return await dispatch_outbound_message(
        target_cid,
        req.phone,
        req.message,
        background_tasks,
        db,
        source_message_internal_id=req.source_message_internal_id,
        suggestion_id=req.suggestion_id,
        variant_style=req.variant_style,
        suggestion_edited=req.suggestion_edited,
    )


@app.post("/api/leads/{lead_id}/human-takeover/toggle")
def toggle_lead_human_takeover(
    lead_id: int,
    data: HumanTakeoverUpdate = HumanTakeoverUpdate(),
    db: Session = Depends(get_db),
    company_id: str = Depends(_resolve_company_id),
):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id, Lead.is_deleted == False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    enabled = (not lead.is_paused) if data.enabled is None else data.enabled
    _apply_human_takeover(db, company_id, lead, enabled, source="workspace_toggle")

    return {
        "success": True,
        "lead_id": lead.id,
        "human_takeover_active": lead.is_paused,
        "is_paused": lead.is_paused,
    }


class CopilotChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    scope: Optional[str] = "company"
    lead_id: Optional[int] = None
    conversation_context: Optional[List[dict]] = None


@app.post("/api/v1/copilot/chat")
async def copilot_chat(request: CopilotChatRequest, db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    from services.velor_chat_service import ask_velor

    try:
        return await ask_velor(db=db, company_id=company_id, message=request.message, scope=request.scope or "company", lead_id=request.lead_id, conversation_context=request.conversation_context)
    except ValueError as exc:
        if str(exc) == "lead_not_found":
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(status_code=500, detail=f"Ask Velor Error: {str(exc)}")


@app.post("/api/v1/copilot/chat/lead/{lead_id}")
async def copilot_chat_lead(
    lead_id: int, 
    request: CopilotChatRequest, 
    db: Session = Depends(get_db), 
    company_id: str = Depends(_resolve_company_id)
):
    from services.velor_chat_service import ask_velor

    try:
        return await ask_velor(db=db, company_id=company_id, message=request.message, scope="lead", lead_id=lead_id, conversation_context=request.conversation_context)
    except ValueError as exc:
        if str(exc) == "lead_not_found":
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(status_code=500, detail=f"Lead Ask Velor Error: {str(exc)}")


# ─────────────────────────────────────────────────


# ─────────────────────────────────────────────────

# Missing endpoints for frontend compatibility
class TogglePauseReq(BaseModel):
    phone: str

@app.post("/whatsapp/agent/toggle-pause")
async def toggle_agent_pause_endpoint(req: TogglePauseReq, db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    new_status = toggle_lead_pause(db, company_id, req.phone)
    return {"success": True, "is_paused": new_status}

@app.get("/whatsapp/agent/pause-status")
async def get_agent_pause_status_endpoint(phone: str, db: Session = Depends(get_db), company_id: str = Depends(_resolve_company_id)):
    status = is_lead_paused(db, company_id, phone)
    return {"success": True, "is_paused": status}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # Exclude SQLite database files from uvicorn hot-reload to prevent disconnects during updates
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1, reload=True, reload_excludes=["*.db", "*.db-wal", "*.db-shm", "*.db-journal"])
