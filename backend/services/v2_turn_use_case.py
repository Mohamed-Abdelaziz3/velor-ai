"""Application use case for one accepted V2 customer turn.

Routes and webhook workers retain ingress validation, claim handling, skips,
delivery, and response shaping. This boundary owns only the shared V2 decision
and atomic persistence hand-off so every customer channel uses the same
application-level sequence.
"""

from typing import Any, Optional

from services import public_chat_turn_service, velor_chat_v2


async def execute_v2_turn(
    *,
    db: Any,
    company: Any,
    lead: Any,
    source_message: Any,
    company_id: str,
    lead_id: int,
    user_id: str,
    customer_text: str,
    inbound_internal_id: str,
    processing_claim_attempt: int,
    background_tasks: Any = None,
    channel_type: str = "VELOR_WEB_CHAT",
    source_route: Optional[str] = None,
    outbound_delivery_status: str = "sent",
    telemetry_source: Optional[str] = None,
    enforce_auto_reply_guard: bool = True,
) -> dict:
    """Generate and atomically persist one V2 turn.

    The caller owns timeout/cancellation policy and all channel-specific
    ingress/delivery decisions. The V2 response engine and the canonical turn
    persistence service remain the only decision and write authorities here.
    """
    result = await velor_chat_v2.get_v2_ai_response(
        db=db,
        source_message=source_message,
        company=company,
        lead=lead,
        background_tasks=background_tasks,
        channel_type=channel_type,
        source_route=source_route,
    )
    trace = result["trace"]
    persisted = public_chat_turn_service.persist_v2_public_turn_atomic(
        db=db,
        company_id=company_id,
        lead_id=lead_id,
        user_id=user_id,
        customer_text=customer_text,
        assistant_text=result["answer_text"],
        inbound_internal_id=inbound_internal_id,
        processing_claim_attempt=processing_claim_attempt,
        lead_update=trace.get("lead_to_save"),
        decision=trace.get("action_decision"),
        sales_snapshot=trace.get("sales_snapshot"),
        objection_snapshot=trace.get("objection_snapshot"),
        recommendation_decision=trace.get("recommendation_decision"),
        response_envelope=result.get("response_envelope"),
        conversation_action=trace.get("conversation_action"),
        trace=trace,
        channel_type=channel_type,
        outbound_delivery_status=outbound_delivery_status,
        telemetry_source=telemetry_source,
        enforce_auto_reply_guard=enforce_auto_reply_guard,
    )
    return {
        "result": result,
        "trace": trace,
        "response_envelope": result.get("response_envelope"),
        "persisted": persisted,
    }
