import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

log = logging.getLogger("adam.workspace_suggestions")


def _draft_context_signals(ctx: Any, plan: Any) -> Dict[str, Any]:
    """Return a compact, customer-safe snapshot shared by every draft variant."""
    return {
        "plan_type": getattr(plan, "plan_type", None),
        "sales_state": getattr(ctx, "canonical_sales_state", None),
        "dialogue_act": getattr(ctx, "dialogue_act", None),
        "objective": getattr(ctx, "objective", None),
        "next_move": getattr(ctx, "next_move", None),
        "objection": getattr(ctx, "objection", None),
        "current_products": list(getattr(ctx, "current_product_references", None) or [])[:3],
        "budget": getattr(ctx, "explicit_budget", None),
        "budget_currency": getattr(ctx, "explicit_budget_currency", None),
        "history_turn_count": len(getattr(ctx, "recent_messages", None) or []),
    }


def _variant_blueprints(ctx: Any, plan: Any) -> Dict[str, Dict[str, str]]:
    next_move = str(getattr(ctx, "next_move", None) or "advance the decision without pressure")
    return {
        "natural": {
            "label": "طبيعي",
            "goal": "answer_in_customer_voice",
            "instruction": "Answer naturally in the customer's established voice and keep continuity with the conversation.",
        },
        "concise": {
            "label": "مختصر",
            "goal": "answer_with_minimum_friction",
            "instruction": "Give the shortest complete answer that still fulfills the latest customer need.",
        },
        "commercially_helpful": {
            "label": "مفيد تجاريًا",
            "goal": "advance_best_next_move_without_pressure",
            "instruction": f"Answer first, then support this verified next move without pressure: {next_move}.",
        },
    }


def _safe_json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _format_price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:g}"


def _serialize_suggestion(suggestion: Any) -> Dict[str, Any]:
    fact_ids = _safe_json_loads(getattr(suggestion, "fact_ids_used", None), [])
    variants = _safe_json_loads(getattr(suggestion, "variants_json", None), [])
    if not variants:
        variants = [
            {
                "style": getattr(suggestion, "style", None) or "natural",
                "label": "طبيعي",
                "text": suggestion.suggested_reply,
                "fact_ids_used": fact_ids,
            }
        ]
    return {
        "id": suggestion.id,
        "lead_id": suggestion.lead_id,
        "company_id": suggestion.company_id,
        "source_message_id": suggestion.source_message_id,
        "source_message_internal_id": suggestion.source_message_internal_id,
        "suggested_reply": suggestion.suggested_reply,
        "why_this_reply": suggestion.why_this_reply,
        "evidence_summary": suggestion.evidence_summary,
        "missing_data": _safe_json_loads(suggestion.missing_data, []),
        "confidence": suggestion.confidence,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        # Additive owner-draft contract. The source message is the version
        # boundary: active_workspace_suggestions marks it stale after any new
        # customer turn, owner reply, or takeover.
        "style": getattr(suggestion, "style", None) or "natural",
        "answers_message_id": suggestion.source_message_id,
        "fact_ids_used": fact_ids,
        "variants": variants,
        "generated_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "context_version": getattr(suggestion, "context_version", None) or "v2",
        "stale_status": suggestion.status == "stale",
        "stale_reason": getattr(suggestion, "stale_reason", None),
    }


def serialize_suggestion(suggestion: Any) -> Dict[str, Any]:
    return _serialize_suggestion(suggestion)


def _summarize_evidence(evidence_rows: List[Any]) -> str:
    labels = {
        "price_question": "Customer asked about price.",
        "product_mention": "Customer mentioned a known configured product.",
        "objection_price": "Customer raised a price concern.",
        "buying_signal": "Customer showed buying interest.",
        "urgency": "Customer signaled urgency.",
        "hesitation": "Customer may need reassurance.",
        "start_intent": "Customer asked how to start.",
    }
    summaries = []
    for row in evidence_rows:
        label = labels.get(row.evidence_type)
        if label and label not in summaries:
            summaries.append(label)
    return " ".join(summaries) or "No strong deterministic evidence was found."


def _build_suggestion_payload(message: Any, lead: Any, evidence_rows: List[Any]) -> Dict[str, Any]:
    evidence_types = {row.evidence_type for row in evidence_rows}
    product_rows = [row for row in evidence_rows if row.evidence_type == "product_mention"]
    first_product = product_rows[0] if product_rows else None
    metadata = _safe_json_loads(first_product.metadata_json, {}) if first_product else {}

    product_name = metadata.get("matched_product_name") or (first_product.normalized_value if first_product else None)
    known_price = metadata.get("known_price")
    currency = metadata.get("currency")
    missing_data = set()

    if "price_question" in evidence_types and not product_name:
        missing_data.add("product")
        missing_data.add("price")
        suggested_reply = "Which product or service would you like the price for? I want to confirm the accurate details for you."
        why = "The customer asked about price, but no configured product was confidently identified."
        confidence = 0.72
    elif product_name and known_price is not None:
        missing_data.add("quantity")
        price_text = _format_price(known_price)
        currency_text = f" {currency}" if currency else ""
        suggested_reply = (
            f"Thanks for your interest in {product_name}. The listed price is {price_text}{currency_text}. "
            "Could you share the quantity or package you need so I can guide you accurately?"
        )
        why = "The product and configured price are known, but quantity is not known."
        confidence = 0.9
    elif product_name:
        missing_data.add("price")
        suggested_reply = (
            f"Thanks for asking about {product_name}. Let me confirm the exact details for you. "
            "Could you share the quantity or what you need it for?"
        )
        why = "The product is known, but no trusted configured price is available."
        confidence = 0.78
    elif "objection_price" in evidence_types:
        missing_data.add("product")
        suggested_reply = (
            "I understand that price matters. Could you tell me which product and quantity you are considering "
            "so I can help with the most accurate option?"
        )
        why = "The customer raised a price concern, but product and quantity are not both known."
        confidence = 0.7
    elif "start_intent" in evidence_types or "buying_signal" in evidence_types:
        suggested_reply = "Happy to help. Could you share which product you are interested in so I can guide you through the next step?"
        why = "The customer showed interest, but the product is not clear enough for a specific reply."
        missing_data.add("product")
        confidence = 0.68
    else:
        suggested_reply = "Thanks for your message. Could you share a bit more about what you need so I can help you accurately?"
        why = "The latest message has limited verified context, so the safest reply asks for clarification."
        confidence = 0.6

    if known_price is None and "price_question" in evidence_types:
        missing_data.add("price")

    return {
        "suggested_reply": suggested_reply,
        "why_this_reply": why,
        "evidence_summary": _summarize_evidence(evidence_rows),
        "missing_data": sorted(missing_data),
        "confidence": confidence,
    }


def _build_shared_grounded_payload(
    db: Session,
    company_id: str,
    message: Any,
    lead: Any,
    evidence_rows: List[Any],
) -> Dict[str, Any]:
    """Use the V2 context, plan, and verifier-safe fallback for owner drafts.

    Suggested replies are advisory only.  This deliberately does not write a
    message, mutate the lead, or use legacy snapshots as a truth source.
    """
    from database import Company
    from services.velor_chat_v2 import build_response_context, build_response_plan, execute_contextual_fallback

    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    if not company:
        return _build_suggestion_payload(message, lead, evidence_rows)

    try:
        ctx = build_response_context(db, message, company, lead)
        plan = build_response_plan(ctx)
        reply = execute_contextual_fallback(ctx, plan)
        context_signals = _draft_context_signals(ctx, plan)
        natural_blueprint = _variant_blueprints(ctx, plan)["natural"]
        resolved = [item for item in (getattr(ctx, "product_resolution", {}) or {}).get("resolved_products", []) if item]
        missing_data = []
        if plan.plan_type in {"PRODUCT_PRICE", "PRODUCT_SELECTION", "PRODUCT_SPECS"} and not resolved:
            missing_data.append("product")
        if resolved and resolved[0].get("price") is None and plan.plan_type in {"PRODUCT_PRICE", "PRODUCT_SELECTION"}:
            missing_data.append("price")
        if resolved and resolved[0].get("price") is not None and plan.plan_type == "PRODUCT_PRICE":
            missing_data.append("quantity")
        if plan.plan_type == "PRICE_OBJECTION" and ctx.explicit_budget is None:
            missing_data.append("budget")
        return {
            "suggested_reply": reply,
            "why_this_reply": "يرد مباشرة على آخر رسالة بالمنتجات والسياسات المسجلة فقط.",
            "evidence_summary": _summarize_evidence(evidence_rows),
            "missing_data": missing_data,
            "confidence": 0.86 if resolved else 0.68,
            "fact_ids_used": [fact.fact_id for fact in plan.allowed_facts],
            "style": "natural",
            "variants": [
                {
                    "style": "natural",
                    "label": natural_blueprint["label"],
                    "text": reply,
                    "fact_ids_used": [fact.fact_id for fact in plan.allowed_facts],
                    "goal": natural_blueprint["goal"],
                    "context_signals": context_signals,
                }
            ],
        }
    except Exception:
        # A draft must never block the owner workflow. The legacy deterministic
        # payload remains a source-bound fallback, not a second authority.
        return _build_suggestion_payload(message, lead, evidence_rows)


def create_workspace_suggestion_for_message(
    db: Session,
    company_id: str,
    user_id: str,
    source_message_internal_id: str,
    skip_reason: str,
) -> Optional[Dict[str, Any]]:
    from database import Lead, LeadEvidence, Message, SystemEvent, WorkspaceSuggestedReply, get_phone_variants, normalize_whatsapp_number

    existing = (
        db.query(WorkspaceSuggestedReply)
        .filter(
            WorkspaceSuggestedReply.company_id == company_id,
            WorkspaceSuggestedReply.source_message_internal_id == source_message_internal_id,
        )
        .first()
    )
    if existing:
        return _serialize_suggestion(existing)

    message = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.internal_message_id == source_message_internal_id)
        .first()
    )
    if not message:
        return None

    base_phone = normalize_whatsapp_number(user_id)
    variants = set(get_phone_variants(base_phone))
    if base_phone:
        variants.add(base_phone)
    variants.add(str(user_id))

    lead = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            (Lead.whatsapp_number.in_(variants)) | (Lead.phone.in_(variants)) | (Lead.whatsapp_jid == str(user_id)) | (Lead.external_customer_id == str(user_id)),
        )
        .first()
    )
    if not lead:
        return None

    # An inbound customer turn is the canonical context-version boundary for
    # every owner draft on this lead.  Apply it before creating the replacement
    # draft so retries remain idempotent and the new draft stays usable.
    invalidate_prior_suggestions_for_inbound_message(
        db,
        company_id=company_id,
        lead_id=lead.id,
        inbound_message_internal_id=source_message_internal_id,
    )

    evidence_rows = (
        db.query(LeadEvidence)
        .filter(LeadEvidence.company_id == company_id, LeadEvidence.message_internal_id == source_message_internal_id)
        .order_by(LeadEvidence.created_at.asc())
        .all()
    )
    payload = _build_shared_grounded_payload(db, company_id, message, lead, evidence_rows)

    suggestion = WorkspaceSuggestedReply(
        company_id=company_id,
        lead_id=lead.id,
        source_message_id=message.id,
        source_message_internal_id=source_message_internal_id,
        suggested_reply=payload["suggested_reply"],
        why_this_reply=payload["why_this_reply"],
        evidence_summary=payload["evidence_summary"],
        missing_data=json.dumps(payload["missing_data"]),
        style=payload.get("style") or "natural",
        context_version=f"v2:{source_message_internal_id}",
        fact_ids_used=json.dumps(payload.get("fact_ids_used") or []),
        variants_json=json.dumps(payload.get("variants") or [], ensure_ascii=False),
        confidence=float(payload["confidence"]),
        status="suggested",
    )
    db.add(suggestion)
    db.flush()
    serialized = _serialize_suggestion(suggestion)

    db.add(
        SystemEvent(
            company_id=company_id,
            event_type="workspace.suggested_reply",
            entity_id=str(suggestion.id),
            payload=json.dumps(
                {
                    **serialized,
                    "type": "workspace.suggested_reply",
                    "user_id": user_id,
                    "phone": lead.whatsapp_number or lead.phone,
                    "auto_reply_skipped_reason": skip_reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    )
    from services.pilot_telemetry_service import record_pilot_event

    record_pilot_event(
        db,
        event_name="suggestion_generated",
        company_id=company_id,
        actor_type="system",
        entity_id=suggestion.id,
        source="workspace_suggestion_created",
        idempotency_key=f"suggestion:{suggestion.id}:generated:{suggestion.context_version}",
        metadata={
            "lead_id": lead.id,
            "suggestion_id": suggestion.id,
            "source_message_internal_id": source_message_internal_id,
        },
        commit=False,
    )
    db.commit()
    return serialized


def active_workspace_suggestions(db: Session, company_id: str, lead: Any, limit: int = 5) -> List[Any]:
    """Return only suggestions still tied to the current customer turn.

    Suggestions are advisory drafts.  They become stale when their source is
    unverifiable, a newer inbound turn exists, an owner has replied after the
    source, or human takeover is active.
    """
    from database import Message, WorkspaceSuggestedReply, get_phone_variants, normalize_whatsapp_number

    suggestions = (
        db.query(WorkspaceSuggestedReply)
        .filter(
            WorkspaceSuggestedReply.company_id == company_id,
            WorkspaceSuggestedReply.lead_id == lead.id,
            WorkspaceSuggestedReply.status == "suggested",
        )
        .order_by(WorkspaceSuggestedReply.created_at.desc())
        .all()
    )
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
    messages = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.user_id.in_(user_ids))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .all()
        if user_ids
        else []
    )
    latest_inbound = next((row for row in messages if row.direction == "incoming" and row.sender in {"user", "customer"}), None)
    active = []
    for suggestion in suggestions:
        source = next((row for row in messages if row.internal_message_id == suggestion.source_message_internal_id), None)
        owner_replied = bool(source and any(
            row.direction == "outgoing" and row.created_at and source.created_at and row.created_at >= source.created_at
            for row in messages
        ))
        stale_reason = None
        if source is None or source.direction != "incoming" or source.sender not in {"user", "customer"}:
            stale_reason = "source_unavailable"
        elif latest_inbound is not None and latest_inbound.internal_message_id != suggestion.source_message_internal_id:
            stale_reason = "new_customer_turn"
        elif owner_replied:
            stale_reason = "owner_replied"
        stale = stale_reason is not None
        if stale:
            suggestion.status = "stale"
            suggestion.stale_reason = stale_reason
        else:
            active.append(suggestion)
    if suggestions:
        db.flush()
    return active[:limit]


def invalidate_company_suggestions(db: Session, company_id: str, reason: str) -> int:
    """Invalidate advisory drafts after catalog/policy authority changes."""
    from database import WorkspaceSuggestedReply

    rows = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company_id,
        WorkspaceSuggestedReply.status == "suggested",
    ).all()
    for row in rows:
        row.status = "stale"
        row.stale_reason = reason[:80]
    if rows:
        db.flush()
    return len(rows)


def invalidate_lead_suggestions(db: Session, company_id: str, lead_id: int, reason: str) -> int:
    """Invalidate drafts that existed before a lead control-state transition."""
    from database import WorkspaceSuggestedReply

    rows = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company_id,
        WorkspaceSuggestedReply.lead_id == lead_id,
        WorkspaceSuggestedReply.status == "suggested",
    ).all()
    for row in rows:
        row.status = "stale"
        row.stale_reason = reason[:80]
    if rows:
        db.flush()
    return len(rows)


def invalidate_prior_suggestions_for_inbound_message(
    db: Session,
    *,
    company_id: str,
    lead_id: int,
    inbound_message_internal_id: str,
) -> int:
    """Make older active drafts unusable when customer context advances.

    This is deliberately a state transition, not a telemetry event.  The
    inbound message has its own exact-once persistence contract, and a retry
    must neither re-transition terminal drafts nor generate duplicate lifecycle
    telemetry.  Tenant, lead, and source-message scoping keeps the new draft
    (when one is created for this same inbound turn) active.
    """
    from database import WorkspaceSuggestedReply

    rows = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company_id,
        WorkspaceSuggestedReply.lead_id == lead_id,
        WorkspaceSuggestedReply.status == "suggested",
        WorkspaceSuggestedReply.source_message_internal_id != inbound_message_internal_id,
    ).all()
    for row in rows:
        row.status = "stale"
        row.stale_reason = "new_customer_turn"
    if rows:
        db.flush()
    return len(rows)


async def regenerate_workspace_suggestion_variants(db: Session, company_id: str, lead_id: int) -> Optional[Dict[str, Any]]:
    """Generate one verified draft group; three variants use one provider call.

    The provider is a language writer only. Every variant is verified against
    the same V2 fact plan. Any provider/config/output failure returns one safe
    contextual fallback and never sends a customer message.
    """
    from database import Company, Lead, LeadEvidence, Message, SystemEvent, WorkspaceSuggestedReply, get_phone_variants, normalize_whatsapp_number
    from services.velor_chat_v2 import (
        ClaimVerifier,
        _get_groq_client,
        _provider_timeout_seconds,
        build_response_context,
        build_response_plan,
        check_provider_readiness,
        execute_contextual_fallback,
        infer_language_profile,
        validate_writer_style,
    )
    from services.fulfillment_verifier import verify_fulfillment

    company = db.query(Company).filter(Company.company_id == company_id, Company.is_deleted == False).first()
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id, Lead.is_deleted == False).first()
    if not company or not lead:
        return None

    user_ids = set()
    for value in (lead.external_customer_id, lead.whatsapp_jid, lead.customer_provided_phone, lead.phone, lead.whatsapp_number):
        if not value:
            continue
        text = str(value)
        user_ids.add(text)
        normalized = normalize_whatsapp_number(text)
        if normalized:
            user_ids.add(normalized)
            user_ids.update(get_phone_variants(normalized))

    def load_latest_turn() -> Optional[Any]:
        return (
            db.query(Message)
            .execution_options(populate_existing=True)
            .filter(
                Message.company_id == company_id,
                Message.user_id.in_(user_ids),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
            if user_ids
            else None
        )

    def still_targets_unanswered_source(source: Any) -> bool:
        current = load_latest_turn()
        return bool(
            current
            and current.id == source.id
            and current.direction == "incoming"
            and current.sender in {"user", "customer"}
        )

    latest_turn = load_latest_turn()
    if (
        not latest_turn
        or latest_turn.direction != "incoming"
        or latest_turn.sender not in {"user", "customer"}
    ):
        return None
    latest = latest_turn

    evidence_rows = db.query(LeadEvidence).filter(
        LeadEvidence.company_id == company_id,
        LeadEvidence.message_internal_id == latest.internal_message_id,
    ).all()
    ctx = build_response_context(db, latest, company, lead)
    plan = build_response_plan(ctx)
    fallback = execute_contextual_fallback(ctx, plan)
    context_signals = _draft_context_signals(ctx, plan)
    blueprints = _variant_blueprints(ctx, plan)
    fallback_fact_ids = [fact.fact_id for fact in plan.allowed_facts]
    variants = [{
        "style": "natural",
        "label": blueprints["natural"]["label"],
        "text": fallback,
        "fact_ids_used": fallback_fact_ids,
        "goal": blueprints["natural"]["goal"],
        "context_signals": context_signals,
    }]
    response_path = "FALLBACK"

    readiness = check_provider_readiness()
    client = _get_groq_client()
    if client:
        allowed_facts = [
            {
                "fact_id": fact.fact_id,
                "type": fact.fact_type,
                "value": fact.value,
                "product": fact.product_key,
            }
            for fact in plan.allowed_facts
        ]
        _language, register = infer_language_profile(latest.message, ctx.merchant_tone)
        conversation_brief = {
            "sales_state": ctx.canonical_sales_state,
            "dialogue_act": ctx.dialogue_act,
            "objective": ctx.objective,
            "next_move": ctx.next_move,
            "objection": ctx.objection,
            "current_products": ctx.current_product_references[:3],
            "budget": ctx.explicit_budget,
            "budget_currency": ctx.explicit_budget_currency,
            "plan_type": plan.plan_type,
            "answer_obligation": plan.answer_obligation.to_dict() if plan.answer_obligation else None,
        }
        instructions = {
            "task": "Create exactly three materially different editable owner reply drafts in one response.",
            "styles": ["natural", "concise", "commercially_helpful"],
            "latest_customer_message": latest.message,
            "register": register,
            "contact_capture_allowed": plan.contact_capture_allowed,
            "allowed_facts": allowed_facts,
            "conversation_brief": conversation_brief,
            "customer_memory": ctx.memory_context,
            "communication_policy": ctx.communication_context,
            "merchant_tone": ctx.merchant_tone,
            "variant_blueprints": [
                {"style": style, **blueprints[style]}
                for style in ("natural", "concise", "commercially_helpful")
            ],
            "rules": [
                "Answer the latest message first.",
                "Use the bounded conversation messages to preserve continuity and avoid repeating answered questions.",
                "Use only cited fact IDs.",
                "Never invent stock, discount, warranty, delivery, price, or specifications.",
                "Do not request contact unless contact_capture_allowed is true.",
                "Fulfill the answer obligation before any next step.",
                "Follow each style's distinct goal and instruction.",
                "Return JSON only: {variants:[{style,text,fact_ids_used}]}",
            ],
        }
        provider_messages = [{"role": "system", "content": json.dumps(instructions, ensure_ascii=False)}]
        for history_item in ctx.recent_messages:
            role = str(history_item.get("role") or "").casefold()
            content = str(history_item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                provider_messages.append({"role": role, "content": content[:1200]})
        provider_messages.append({"role": "user", "content": latest.message})
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=readiness["model_name"],
                    messages=provider_messages,
                    temperature=0.25,
                    max_tokens=650,
                    response_format={"type": "json_object"},
                ),
                timeout=_provider_timeout_seconds(),
            )
            data = json.loads(response.choices[0].message.content)
            candidates = data.get("variants") if isinstance(data, dict) else None
            expected_styles = {"natural", "concise", "commercially_helpful"}
            verified = []
            for candidate in candidates or []:
                if not isinstance(candidate, dict):
                    continue
                style = str(candidate.get("style") or "")
                text = str(candidate.get("text") or "").strip()
                fact_ids = candidate.get("fact_ids_used") or []
                if style not in expected_styles or not text or len(text) > 700:
                    continue
                ok, _violations = ClaimVerifier.verify(text, plan, ctx, fact_ids_used=fact_ids)
                fulfillment = verify_fulfillment(text, plan.answer_obligation)
                style_violations = validate_writer_style(text, ctx)
                if ok and fulfillment.passed and not style_violations:
                    verified.append({
                        "style": style,
                        "label": blueprints[style]["label"],
                        "text": text,
                        "fact_ids_used": fact_ids,
                        "goal": blueprints[style]["goal"],
                        "context_signals": context_signals,
                    })
                else:
                    log.info(
                        "Rejected owner draft variant style=%s claim=%s fulfillment=%s style_checks=%s",
                        style,
                        _violations,
                        list(fulfillment.violations),
                        style_violations,
                    )
            if len(verified) == 3 and len({item["text"].casefold() for item in verified}) == 3 and {item["style"] for item in verified} == expected_styles:
                variants = verified
                response_path = "MODEL"
        except Exception as exc:
            # The fallback remains the product contract; provider details are
            # exposed only through sanitized V2 diagnostics.
            log.warning("Owner draft provider generation failed category=%s", exc.__class__.__name__)
            variants = variants[:1]

    # The provider await is an explicit race boundary. Never publish a draft
    # for a turn that was answered or superseded while generation was running.
    if not still_targets_unanswered_source(latest):
        return None

    existing = (
        db.query(WorkspaceSuggestedReply)
        .filter(
            WorkspaceSuggestedReply.company_id == company_id,
            WorkspaceSuggestedReply.source_message_internal_id == latest.internal_message_id,
        )
        .with_for_update()
        .first()
    )
    suggestion = existing
    if suggestion is None:
        try:
            # The unique source-message constraint is the idempotency fence.
            # A savepoint lets a concurrent winner be reloaded without putting
            # the whole request session into a failed transaction state.
            with db.begin_nested():
                suggestion = WorkspaceSuggestedReply(
                    company_id=company_id,
                    lead_id=lead.id,
                    source_message_id=latest.id,
                    source_message_internal_id=latest.internal_message_id,
                    suggested_reply=variants[0]["text"],
                )
                db.add(suggestion)
                db.flush()
        except IntegrityError:
            suggestion = (
                db.query(WorkspaceSuggestedReply)
                .filter(
                    WorkspaceSuggestedReply.company_id == company_id,
                    WorkspaceSuggestedReply.source_message_internal_id == latest.internal_message_id,
                )
                .with_for_update()
                .first()
            )
            if suggestion is None:
                raise

    suggestion.suggested_reply = variants[0]["text"]
    suggestion.why_this_reply = "يرد على آخر رسالة من السياق والحقائق الموثقة فقط."
    suggestion.evidence_summary = _summarize_evidence(evidence_rows)
    suggestion.missing_data = json.dumps(sorted(set(getattr(plan, "unknown_slots", None) or [])))
    suggestion.style = variants[0]["style"]
    suggestion.context_version = f"v2:{latest.internal_message_id}"
    suggestion.fact_ids_used = json.dumps(sorted({fact_id for variant in variants for fact_id in variant.get("fact_ids_used", [])}))
    suggestion.variants_json = json.dumps(variants, ensure_ascii=False)
    suggestion.stale_reason = None
    suggestion.status = "suggested"
    suggestion.confidence = 0.9 if response_path == "MODEL" else 0.82
    db.flush()

    # Re-check immediately before the SSE write/commit as a second fence for
    # owner replies that race the local persistence work above.
    if not still_targets_unanswered_source(latest):
        db.rollback()
        return None

    serialized = _serialize_suggestion(suggestion)
    serialized["response_path"] = response_path
    workspace_event = SystemEvent(
        company_id=company_id,
        event_type="workspace.suggested_reply",
        entity_id=str(suggestion.id),
        payload=json.dumps({**serialized, "type": "workspace.suggested_reply"}, ensure_ascii=False),
    )
    db.add(workspace_event)
    db.flush()
    from services.pilot_telemetry_service import record_pilot_event

    record_pilot_event(
        db,
        event_name="suggestion_generated",
        company_id=company_id,
        actor_type="system",
        entity_id=suggestion.id,
        source="workspace_suggestion_regenerated",
        idempotency_key=f"suggestion:{suggestion.id}:generated:event:{workspace_event.id}",
        metadata={
            "lead_id": lead.id,
            "suggestion_id": suggestion.id,
            "source_message_internal_id": latest.internal_message_id,
        },
        commit=False,
    )
    db.commit()
    return serialized
