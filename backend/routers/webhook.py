import os
import asyncio
import logging
import httpx
import json
import hashlib
import hmac
import secrets
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from fastapi.responses import Response, JSONResponse
from datetime import datetime, timezone, timedelta
from sqlalchemy.exc import IntegrityError

from database import (
    SessionLocal,
    Lead,
    Message,
    SystemEvent,
    normalize_whatsapp_number,
    Company,
    WebhookInbox,
    get_monthly_usage,
    _upsert_usage_in_session,
)
from services.context_engine import summarize_conversation
from services.message_delivery import apply_message_delivery_update
from services.processing_claim import acquire_inbound_processing_claim, finalize_inbound_processing_claim, ClaimResult
from brain import get_ai_response
from plan_config import check_message_quota

logger = logging.getLogger("adam.webhook")
router = APIRouter()

ENABLE_META_WEBHOOK = os.getenv("ENABLE_META_WEBHOOK", "false").strip().lower() in {"1", "true", "yes", "on"}
VELOR_META_VERIFY_TOKEN = os.getenv("VELOR_META_VERIFY_TOKEN", "")
META_GRAPH_API_TOKEN = os.getenv("META_GRAPH_API_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")
META_COMPANY_ID = os.getenv("META_COMPANY_ID", "")
META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v17.0")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")


class MetaDeliveryStatusNotLinked(RuntimeError):
    """A delivery receipt arrived before its outbound message was linkable."""


def _reject_if_meta_webhook_disabled() -> None:
    if not ENABLE_META_WEBHOOK:
        raise HTTPException(status_code=404, detail="Meta webhook disabled")


def _validate_meta_signature(body: bytes, signature_header: str | None) -> None:
    """Fail closed for enabled Meta POSTs using X-Hub-Signature-256."""
    if not META_APP_SECRET:
        raise HTTPException(status_code=503, detail="Meta webhook signature secret is not configured")
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    expected = "sha256=" + hmac.new(META_APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not secrets.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.get("/api/whatsapp/webhook")
async def verify_webhook(request: Request):
    """
    Handles Meta's hub.verify_token validation.
    """
    _reject_if_meta_webhook_disabled()
    if not VELOR_META_VERIFY_TOKEN:
        raise HTTPException(status_code=503, detail="Meta webhook verify token is not configured")

    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and secrets.compare_digest(token, VELOR_META_VERIFY_TOKEN):
            logger.info("Meta Webhook Verified Successfully.")
            return Response(content=challenge, media_type="text/plain", status_code=200)
        else:
            logger.warning("Meta Webhook Verification Failed: Token Mismatch.")
            raise HTTPException(status_code=403, detail="Verification failed")

    return JSONResponse(status_code=400, content={"message": "Invalid request"})


def _publish_message_delivery_update(db, company_id: str, internal_message_id: str, status: str, wa_message_id: str = None) -> None:
    if not internal_message_id:
        return

    msg = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.internal_message_id == internal_message_id)
        .first()
    )
    if not msg:
        logger.warning("Cannot update delivery status; message %s was not found.", internal_message_id)
        return

    apply_message_delivery_update(
        db,
        msg,
        status,
        provider_message_id=wa_message_id,
    )


async def send_whatsapp_message(phone: str, text: str) -> dict:
    """
    Dispatches the generated message back to the WhatsApp API.
    """
    if not META_GRAPH_API_TOKEN or not META_PHONE_NUMBER_ID:
        raise RuntimeError("Meta Graph API credentials missing. Cannot dispatch to WhatsApp.")

    url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {META_GRAPH_API_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": text}}

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        wa_message_id = None
        if isinstance(data, dict):
            messages = data.get("messages") or []
            if messages and isinstance(messages[0], dict):
                wa_message_id = messages[0].get("id")
        logger.info("Successfully dispatched a Meta message; recipient and raw provider response are not logged")
        return {"success": True, "wa_message_id": wa_message_id}


def _meta_provider_event_id(payload: dict) -> str | None:
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []) or []:
                    if message.get("id"):
                        return str(message["id"])[:128]
                for status in value.get("statuses", []) or []:
                    if status.get("id"):
                        return str(status["id"])[:128]
    except Exception:
        return None
    return None


def _persist_meta_webhook_inbox(body: bytes, payload: dict) -> WebhookInbox:
    payload_hash = hashlib.sha256(body).hexdigest()
    provider_event_id = _meta_provider_event_id(payload)
    with SessionLocal() as db:
        existing = (
            db.query(WebhookInbox)
            .filter(WebhookInbox.payload_hash == payload_hash)
            .first()
        )
        if existing is not None:
            db.expunge(existing)
            return existing
        item = WebhookInbox(
            provider="meta",
            payload_hash=payload_hash,
            provider_event_id=provider_event_id,
            company_id=(META_COMPANY_ID or None),
            payload_json=json.dumps(payload, ensure_ascii=False),
            status="pending",
            attempts=0,
        )
        db.add(item)
        try:
            db.commit()
            db.refresh(item)
            db.expunge(item)
            return item
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(WebhookInbox)
                .filter(WebhookInbox.payload_hash == payload_hash)
                .first()
            )
            if existing is None:
                raise
            db.expunge(existing)
            return existing


async def process_webhook_inbox_item(inbox_id: int) -> bool:
    """Claim and process one durable webhook item at most once concurrently."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(
        seconds=int(os.getenv("WEBHOOK_INBOX_STALE_SECONDS", "180"))
    )
    max_attempts = max(
        1,
        int(os.getenv("WEBHOOK_INBOX_MAX_ATTEMPTS", "8")),
    )

    with SessionLocal() as db:
        item = db.query(WebhookInbox).filter(WebhookInbox.id == inbox_id).first()
        if item is None or item.status in {"completed", "dead_letter"}:
            return False
        processing_started = item.processing_started_at
        if processing_started is not None and processing_started.tzinfo is None:
            processing_started = processing_started.replace(tzinfo=timezone.utc)
        if (
            item.status == "processing"
            and processing_started is not None
            and processing_started > stale_before
        ):
            return False
        if item.attempts >= max_attempts:
            item.status = "dead_letter"
            item.processed_at = now
            db.commit()
            logger.error(
                "Meta webhook inbox item %s moved to dead letter after %s attempts",
                inbox_id,
                item.attempts,
            )
            return False

        previous_status = item.status
        previous_attempts = item.attempts
        updated = (
            db.query(WebhookInbox)
            .filter(
                WebhookInbox.id == inbox_id,
                WebhookInbox.status == previous_status,
                WebhookInbox.attempts == previous_attempts,
            )
            .update(
                {
                    WebhookInbox.status: "processing",
                    WebhookInbox.processing_started_at: now,
                    WebhookInbox.attempts: WebhookInbox.attempts + 1,
                    WebhookInbox.last_error_category: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if updated != 1:
            return False
        payload_json = item.payload_json

    try:
        payload = json.loads(payload_json)
        await process_webhook_payload(payload)
    except Exception as exc:
        with SessionLocal() as db:
            db.query(WebhookInbox).filter(WebhookInbox.id == inbox_id).update(
                {
                    WebhookInbox.status: "failed",
                    WebhookInbox.last_error_category: exc.__class__.__name__[:120],
                    WebhookInbox.processed_at: None,
                },
                synchronize_session=False,
            )
            db.commit()
        logger.error(
            "Meta webhook inbox item %s failed category=%s",
            inbox_id,
            exc.__class__.__name__,
        )
        return False

    with SessionLocal() as db:
        db.query(WebhookInbox).filter(WebhookInbox.id == inbox_id).update(
            {
                WebhookInbox.status: "completed",
                WebhookInbox.processed_at: datetime.now(timezone.utc),
                WebhookInbox.last_error_category: None,
            },
            synchronize_session=False,
        )
        db.commit()
    return True


def recover_pending_webhook_inbox(limit: int = 50) -> int:
    """Scheduler entry point for webhook tasks lost after provider ACK."""
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=int(os.getenv("WEBHOOK_INBOX_STALE_SECONDS", "180"))
    )
    with SessionLocal() as db:
        ids = [
            row.id
            for row in (
                db.query(WebhookInbox)
                .filter(
                    WebhookInbox.provider == "meta",
                    (
                        WebhookInbox.status.in_(["pending", "failed"])
                        | (
                            (WebhookInbox.status == "processing")
                            & (
                                (WebhookInbox.processing_started_at.is_(None))
                                | (WebhookInbox.processing_started_at < stale_before)
                            )
                        )
                    ),
                )
                .order_by(WebhookInbox.created_at.asc())
                .limit(max(1, min(limit, 200)))
                .all()
            )
        ]
    processed = 0
    for inbox_id in ids:
        try:
            if asyncio.run(process_webhook_inbox_item(inbox_id)):
                processed += 1
        except Exception as exc:
            logger.error(
                "Webhook inbox recovery failed id=%s category=%s",
                inbox_id,
                exc.__class__.__name__,
            )
    return processed


def _resolve_meta_company(db, meta_phone_id: str | None) -> Company | None:
    mapped_company_id = None
    raw_mapping = os.getenv("META_PHONE_COMPANY_MAP", "").strip()
    if raw_mapping and meta_phone_id:
        try:
            parsed_mapping = json.loads(raw_mapping)
            if isinstance(parsed_mapping, dict):
                mapped_company_id = parsed_mapping.get(str(meta_phone_id))
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.error("META_PHONE_COMPANY_MAP is not valid JSON")
    company_id = mapped_company_id or META_COMPANY_ID
    if not company_id:
        return None
    return (
        db.query(Company)
        .filter(
            Company.company_id == str(company_id),
            Company.is_deleted == False,
        )
        .first()
    )


def _process_meta_delivery_statuses(value: dict) -> None:
    statuses = value.get("statuses", []) or []
    if not statuses:
        return
    meta_phone_id = (value.get("metadata") or {}).get("phone_number_id")
    with SessionLocal() as db:
        company = _resolve_meta_company(db, meta_phone_id)
        if company is None:
            logger.error(
                "No company mapping for Meta delivery status phone_number_id=%s",
                meta_phone_id,
            )
            return
        unlinked_provider_ids = []
        for status_payload in statuses:
            provider_message_id = status_payload.get("id")
            delivery_status = str(status_payload.get("status") or "").casefold()
            if (
                not provider_message_id
                or delivery_status not in {"sent", "delivered", "read", "failed"}
            ):
                continue
            message = (
                db.query(Message)
                .filter(
                    Message.company_id == company.company_id,
                    Message.wa_message_id == str(provider_message_id),
                    Message.direction == "outgoing",
                )
                .first()
            )
            if message is None:
                recipient_id = str(status_payload.get("recipient_id") or "").strip()
                normalized_recipient = (
                    normalize_whatsapp_number(recipient_id)
                    if recipient_id
                    else ""
                )
                candidate_query = db.query(Message.id).filter(
                    Message.company_id == company.company_id,
                    Message.direction == "outgoing",
                    Message.wa_message_id.is_(None),
                    Message.delivery_status.in_(["pending", "sent", "failed"]),
                    Message.created_at
                    >= datetime.now(timezone.utc) - timedelta(minutes=10),
                )
                if normalized_recipient:
                    candidate_query = candidate_query.filter(
                        Message.user_id.in_([recipient_id, normalized_recipient])
                    )
                if candidate_query.first() is not None:
                    logger.warning(
                        "Meta delivery status arrived before its outgoing message id was linked"
                    )
                    unlinked_provider_ids.append(str(provider_message_id))
                else:
                    logger.info(
                        "Ignored Meta delivery status for an untracked outgoing message"
                    )
                continue
            _publish_message_delivery_update(
                db,
                company.company_id,
                message.internal_message_id,
                delivery_status,
                str(provider_message_id),
            )
        if unlinked_provider_ids:
            # Meta callbacks may beat the HTTP send response that attaches the
            # provider id to our pending outbound row.  Failing the durable
            # inbox attempt makes the scheduler retry instead of silently
            # discarding the receipt.
            raise MetaDeliveryStatusNotLinked(
                f"{len(unlinked_provider_ids)} delivery receipt(s) are not linkable yet"
            )


def _ensure_meta_v2_lead(
    db,
    *,
    company_id: str,
    phone: str,
    client_name: str,
) -> Lead:
    lead = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            (
                (Lead.whatsapp_number == phone)
                | (Lead.phone == phone)
                | (Lead.external_customer_id == phone)
            ),
            Lead.is_deleted == False,
        )
        .first()
    )
    if lead is not None:
        return lead

    lead = Lead(
        company_id=company_id,
        phone=phone,
        whatsapp_number=phone,
        whatsapp_jid=phone,
        external_customer_id=phone,
        channel_type="WHATSAPP_META",
        name=(client_name or "عميل محتمل")[:200],
        status="new",
        stage="Information Gathering",
        conversation_count=0,
    )
    db.add(lead)
    db.flush()
    _upsert_usage_in_session(db, company_id, leads=1)
    db.add(
        SystemEvent(
            company_id=company_id,
            event_type="lead.created",
            entity_id=phone,
            payload=json.dumps(
                {
                    "lead_id": lead.id,
                    "channel": "WHATSAPP_META",
                    "source": "meta_webhook_v2",
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    db.refresh(lead)
    return lead


async def _process_meta_message_v2(
    *,
    db,
    company: Company,
    raw_phone: str,
    phone: str,
    text_body: str,
    external_message_id: str,
    client_name: str,
) -> None:
    from services.public_chat_turn_service import (
        cancel_persisted_auto_reply,
        current_auto_reply_block_reason,
        find_reply_for_inbound,
    )
    from services.v2_turn_use_case import execute_v2_turn

    if not external_message_id:
        logger.warning("Dropped Meta V2 message without a provider message id")
        return

    lead = _ensure_meta_v2_lead(
        db,
        company_id=company.company_id,
        phone=phone,
        client_name=client_name,
    )
    auto_reply_allowed = (
        not lead.is_paused
        and getattr(company, "bot_auto_reply_enabled", True)
    )
    if not auto_reply_allowed:
        reason = (
            "human_takeover_active"
            if lead.is_paused
            else "company_auto_reply_disabled"
        )
        claim_result, inbound = acquire_inbound_processing_claim(
            db,
            company.company_id,
            phone,
            external_message_id,
            text_body,
            defer_side_effects=False,
            commit=True,
        )
        if claim_result in {ClaimResult.CLAIM_ACQUIRED, ClaimResult.RETRYABLE_RECLAIMED} and inbound:
            db.add(
                SystemEvent(
                    company_id=company.company_id,
                    event_type="auto_reply.skipped",
                    entity_id=inbound.internal_message_id,
                    payload=json.dumps(
                        {
                            "reason": reason,
                            "channel": "WHATSAPP_META",
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            db.commit()
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
                    phone,
                    inbound.internal_message_id,
                    reason,
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Workspace suggested reply generation failed for Meta V2 skipped message %s: %s",
                    inbound.internal_message_id,
                    exc,
                )
        return

    monthly_messages, _ = get_monthly_usage(db, company.company_id)
    if not check_message_quota(company.plan, monthly_messages):
        claim_result, inbound = acquire_inbound_processing_claim(
            db,
            company.company_id,
            phone,
            external_message_id,
            text_body,
            defer_side_effects=False,
            commit=True,
        )
        if claim_result in {ClaimResult.CLAIM_ACQUIRED, ClaimResult.RETRYABLE_RECLAIMED} and inbound:
            db.add(
                SystemEvent(
                    company_id=company.company_id,
                    event_type="auto_reply.skipped",
                    entity_id=inbound.internal_message_id,
                    payload=json.dumps(
                        {
                            "reason": "quota_exhausted",
                            "channel": "WHATSAPP_META",
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            db.commit()
            finalize_inbound_processing_claim(
                db,
                inbound.internal_message_id,
                "skipped",
                expected_attempts=inbound.processing_attempts,
            )
        logger.warning(
            "Meta V2 message persisted without auto-reply because the tenant quota is exhausted"
        )
        return

    claim_result, inbound = acquire_inbound_processing_claim(
        db,
        company.company_id,
        phone,
        external_message_id,
        text_body,
        defer_side_effects=True,
        commit=False,
    )
    if claim_result in {
        ClaimResult.ALREADY_PROCESSING,
        ClaimResult.INTENTIONALLY_SKIPPED,
        ClaimResult.UNKNOWN_UNSAFE,
    }:
        return

    if claim_result == ClaimResult.COMPLETED and inbound is not None:
        existing_reply, _ = find_reply_for_inbound(
            db,
            company_id=company.company_id,
            user_id=phone,
            inbound=inbound,
        )
        if existing_reply is None:
            return
        if (
            existing_reply.delivery_status in {"sent", "delivered", "read"}
            and existing_reply.wa_message_id
        ):
            return
        try:
            dispatch = await send_whatsapp_message(raw_phone, existing_reply.message)
            _publish_message_delivery_update(
                db,
                company.company_id,
                existing_reply.internal_message_id,
                "sent",
                dispatch.get("wa_message_id") if dispatch else None,
            )
        except Exception as exc:
            logger.error(
                "Failed to redeliver cached Meta V2 reply category=%s",
                exc.__class__.__name__,
            )
            _publish_message_delivery_update(
                db,
                company.company_id,
                existing_reply.internal_message_id,
                "failed",
            )
            raise
        return

    if inbound is None:
        return

    try:
        turn = await execute_v2_turn(
            db=db,
            company=company,
            lead=lead,
            source_message=inbound,
            company_id=company.company_id,
            lead_id=lead.id,
            user_id=phone,
            customer_text=text_body,
            inbound_internal_id=inbound.internal_message_id,
            processing_claim_attempt=inbound.processing_attempts,
            background_tasks=None,
            channel_type="WHATSAPP_META",
            source_route="/api/whatsapp/webhook",
            outbound_delivery_status="pending",
            telemetry_source="meta_whatsapp",
            enforce_auto_reply_guard=True,
        )
        result = turn["result"]
        trace = turn["trace"]
        persisted = turn["persisted"]
    except Exception as exc:
        db.rollback()
        logger.error(
            "Meta V2 generation/persistence failed category=%s",
            exc.__class__.__name__,
        )
        raise

    if not persisted:
        raise RuntimeError("meta_v2_turn_superseded")
    if persisted.get("auto_reply_skipped"):
        return

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
        return

    try:
        dispatch = await send_whatsapp_message(raw_phone, result["answer_text"])
        _publish_message_delivery_update(
            db,
            company.company_id,
            persisted["internal_id"],
            "sent",
            dispatch.get("wa_message_id") if dispatch else None,
        )
    except Exception as exc:
        logger.error(
            "Failed to dispatch Meta V2 reply category=%s",
            exc.__class__.__name__,
        )
        _publish_message_delivery_update(
            db,
            company.company_id,
            persisted["internal_id"],
            "failed",
        )
        raise

    try:
        await summarize_conversation(company.company_id, phone)
    except Exception as exc:
        logger.warning(
            "Meta V2 post-send summary failed category=%s",
            exc.__class__.__name__,
        )


async def process_webhook_payload(payload: dict):
    """
    Background Task to handle incoming webhook payload robustly.
    Now an async function to avoid blocking thread pools with manual event loops.
    """
    if not ENABLE_META_WEBHOOK:
        logger.warning("Dropped Meta webhook payload because ENABLE_META_WEBHOOK is disabled.")
        return

    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                metadata = value.get("metadata", {})
                _process_meta_delivery_statuses(value)

                if not messages:
                    continue

                # Meta can batch multiple customer messages in one change.
                # Re-enter with one logical message per payload so every item
                # receives an independent processing claim and atomic turn.
                if len(messages) > 1:
                    for message in messages:
                        single_value = dict(value)
                        single_value["messages"] = [message]
                        single_value["statuses"] = []
                        await process_webhook_payload(
                            {
                                "entry": [
                                    {
                                        "changes": [
                                            {
                                                **change,
                                                "value": single_value,
                                            }
                                        ]
                                    }
                                ]
                            }
                        )
                    continue

                message_obj = messages[0]
                contact_obj = contacts[0] if contacts else {}

                if message_obj.get("type") != "text":
                    continue  # Only handling text for now

                raw_phone = message_obj.get("from")
                external_message_id = message_obj.get("id")
                text_body = message_obj.get("text", {}).get("body", "")
                client_name = contact_obj.get("profile", {}).get("name", "Unknown")
                meta_phone_id = metadata.get("phone_number_id")

                if not raw_phone or not text_body:
                    continue

                phone = normalize_whatsapp_number(raw_phone)

                # Instantiate an isolated DB session for the background task
                with SessionLocal() as db:
                    company = _resolve_meta_company(db, meta_phone_id)

                    if not company:
                        logger.error(
                            "No configured company mapping for Meta Phone ID %s. Dropping Meta webhook message.",
                            meta_phone_id,
                        )
                        continue

                    company_id = company.company_id

                    from services.conversation_engine_config import (
                        get_whatsapp_response_engine,
                    )

                    if get_whatsapp_response_engine() == "v2":
                        await _process_meta_message_v2(
                            db=db,
                            company=company,
                            raw_phone=raw_phone,
                            phone=phone,
                            text_body=text_body,
                            external_message_id=external_message_id,
                            client_name=client_name,
                        )
                        continue

                    # Upsert Lead
                    lead = db.query(Lead).filter(Lead.company_id == company_id, (Lead.whatsapp_number == phone) | (Lead.phone == phone)).first()

                    if not lead:
                        lead = Lead(
                            company_id=company_id, phone=phone, whatsapp_number=phone, name=client_name, status="new", stage="Information Gathering"
                        )
                        db.add(lead)
                        db.commit()
                        db.refresh(lead)
                        logger.info("Created a new tenant-scoped lead from a verified Meta webhook")

                    db.refresh(lead)

                    inc_msg = None
                    inc_internal_id = None
                    processing_claim_attempt = None
                    if external_message_id:
                        claim_result, inc_msg = acquire_inbound_processing_claim(
                            db, company_id, phone, external_message_id, text_body
                        )

                        if claim_result == ClaimResult.ALREADY_PROCESSING:
                            logger.info(
                                "Duplicate WhatsApp webhook for message %s is already processing; skipping duplicate execution",
                                external_message_id,
                            )
                            continue

                        if claim_result == ClaimResult.INTENTIONALLY_SKIPPED:
                            logger.info(
                                "WhatsApp message %s was intentionally skipped; suppressing duplicate processing",
                                external_message_id,
                            )
                            continue

                        if claim_result == ClaimResult.UNKNOWN_UNSAFE:
                            logger.warning(
                                "Unknown processing state for WhatsApp message %s; terminating safely",
                                external_message_id,
                            )
                            continue

                        if claim_result == ClaimResult.COMPLETED:
                            existing_incoming = inc_msg
                            if existing_incoming:
                                existing_reply = (
                                    db.query(Message)
                                    .filter(
                                        Message.company_id == company_id,
                                        Message.user_id == phone,
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
                                        logger.info(
                                            "Duplicate retry suppressed: reply %s already delivered (status=%s)",
                                            existing_reply.internal_message_id,
                                            existing_reply.delivery_status,
                                        )
                                        continue

                                    if existing_reply.message:
                                        logger.info(
                                            "Redelivering cached reply %s (status=%s) without AI regeneration",
                                            existing_reply.internal_message_id,
                                            existing_reply.delivery_status,
                                        )
                                        try:
                                            dispatch = await send_whatsapp_message(raw_phone, existing_reply.message)
                                            _publish_message_delivery_update(
                                                db,
                                                company_id,
                                                existing_reply.internal_message_id,
                                                "sent",
                                                dispatch.get("wa_message_id") if dispatch else None,
                                            )
                                        except Exception as send_exc:
                                            logger.error("Failed to redeliver cached Meta reply category=%s", send_exc.__class__.__name__)
                                            _publish_message_delivery_update(db, company_id, existing_reply.internal_message_id, "failed")
                            continue

                        if inc_msg:
                            inc_internal_id = inc_msg.internal_message_id
                            processing_claim_attempt = inc_msg.processing_attempts

                    auto_reply_allowed = (not lead.is_paused) and getattr(company, "bot_auto_reply_enabled", True)

                    if auto_reply_allowed:
                        try:
                            from fastapi import BackgroundTasks

                            bg = BackgroundTasks()

                            # Native await - No thread blocking!
                            reply, internal_id = await get_ai_response(
                                db=db,
                                user_input=text_body,
                                user_id=phone,
                                company_id=company_id,
                                background_tasks=bg,
                                incoming_wa_message_id=external_message_id,
                                persist_incoming=False if inc_msg else True,
                                processing_claim_internal_id=inc_internal_id,
                                processing_claim_attempt=processing_claim_attempt,
                            )

                            if reply:
                                try:
                                    dispatch = await send_whatsapp_message(raw_phone, reply)
                                    _publish_message_delivery_update(
                                        db,
                                        company_id,
                                        internal_id,
                                        "sent",
                                        dispatch.get("wa_message_id") if dispatch else None,
                                    )
                                except Exception as send_exc:
                                    logger.error("Failed to dispatch Meta auto-reply category=%s", send_exc.__class__.__name__)
                                    _publish_message_delivery_update(db, company_id, internal_id, "failed")
                                await summarize_conversation(company_id, phone)
                                if inc_internal_id:
                                    finalize_inbound_processing_claim(
                                        db,
                                        inc_internal_id,
                                        "completed",
                                        expected_attempts=processing_claim_attempt,
                                    )
                            else:
                                if inc_internal_id:
                                    finalize_inbound_processing_claim(
                                        db,
                                        inc_internal_id,
                                        "skipped",
                                        expected_attempts=processing_claim_attempt,
                                    )

                        except Exception as e:
                            logger.error(f"Failed to generate auto-reply: {e}")
                            if inc_internal_id:
                                finalize_inbound_processing_claim(
                                    db,
                                    inc_internal_id,
                                    "failed",
                                    expected_attempts=processing_claim_attempt,
                                )
                    else:
                        logger.info("Meta auto-reply bypassed because takeover or company control is active")
                        if inc_internal_id:
                            finalize_inbound_processing_claim(
                                db,
                                inc_internal_id,
                                "skipped",
                                expected_attempts=processing_claim_attempt,
                            )

                    db.refresh(lead)
                    update_event = SystemEvent(
                        company_id=company_id, event_type="lead.updated", payload=json.dumps({"phone": phone, "intent_score": lead.intent_score or 0})
                    )
                    db.add(update_event)
                    db.commit()

    except Exception as exc:
        logger.error("Webhook payload processing failed category=%s", exc.__class__.__name__)
        if isinstance(exc, MetaDeliveryStatusNotLinked):
            raise
        from services.conversation_engine_config import get_whatsapp_response_engine

        if get_whatsapp_response_engine() == "v2":
            raise
@router.post("/api/whatsapp/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Durably records Meta payloads before acknowledging them, then delegates
    processing to an idempotent inbox worker.
    """
    _reject_if_meta_webhook_disabled()
    try:
        body = await request.body()
        _validate_meta_signature(body, request.headers.get("x-hub-signature-256"))
        payload = json.loads(body)
        try:
            inbox_item = _persist_meta_webhook_inbox(body, payload)
        except Exception as exc:
            logger.error(
                "Failed to durably persist Meta webhook category=%s",
                exc.__class__.__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="Webhook ingress temporarily unavailable",
            ) from exc
        if inbox_item.status != "completed":
            background_tasks.add_task(
                process_webhook_inbox_item,
                inbox_item.id,
            )

        return Response(content="OK", status_code=200)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to parse webhook JSON category=%s", exc.__class__.__name__)
        return Response(content="Bad Request", status_code=400)
