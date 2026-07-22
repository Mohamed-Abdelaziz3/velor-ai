"""Fallback-only real-route campaign for final VELOR conversation closure.

The report deliberately records aggregate counts, routing labels, status codes,
and timings only.  It never writes visitor identifiers, bearer tokens, request
text, or assistant prose to the evidence artifact.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from jose import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal, SystemEvent


ADVERSARIAL_TURNS = (
    "الوان الكرسي ايه؟",
    "وصلني الطلب؟",
    "معايا مشكلة في الكرسي",
    "اخر موديل ايه؟",
    "مش عايز اكلم حد",
    "ما تتصلش بيا",
    "مش غالي",
    "ادفع ازاي واطلب؟",
    "وصلني بخدمة العملاء",
    "فيه تقسيط؟",
    "Ergo One بكام؟",
    "قارن Ergo One و Ergo Pro",
    "ميزانيتي 7000 جنيه",
    "الكرسي بيتحمل 200 كيلو؟",
    "شكرا",
    "ألو",
)

EXPECTED_COLLISIONS = {
    "الوان الكرسي ايه؟": "PRODUCT_DETAILS",
    "وصلني الطلب؟": "DELIVERY_STATUS",
    "معايا مشكلة في الكرسي": "CLARIFICATION",
    "اخر موديل ايه؟": "PRODUCT_DISCOVERY",
    "مش عايز اكلم حد": "CLARIFICATION",
    "ما تتصلش بيا": "CALLBACK_DECLINED",
    "مش غالي": "CLARIFICATION",
    "ادفع ازاي واطلب؟": "PAYMENT_PROCESS",
}


# The public route intentionally limits a client IP to 20 chat turns/minute
# and a tenant to 60/minute.  Reuse a small set of visitor sessions and pace
# the campaign below those production limits instead of disabling them for
# acceptance evidence.
# One bounded session per loopback source keeps every real HTTP request below
# the per-IP, per-visitor, and tenant limits without altering route settings.
CAMPAIGN_SESSION_POOL_SIZE = 12
CAMPAIGN_SOURCE_IPS = tuple(f"127.0.0.{index}" for index in range(2, 2 + CAMPAIGN_SESSION_POOL_SIZE))
# 1.05 seconds remains below the tenant-wide 60-turn/minute limit while the
# source pool independently keeps IP and visitor counters below their limits.
CAMPAIGN_TURN_INTERVAL_SECONDS = 1.05


class CampaignFailure(RuntimeError):
    pass


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 3)


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> tuple[httpx.Response, float]:
    started = time.perf_counter()
    response = await client.request(method, path, **kwargs)
    return response, round((time.perf_counter() - started) * 1000, 3)


async def _new_session(client: httpx.AsyncClient, slug: str) -> tuple[str, dict[str, Any], float]:
    response, latency = await _request(client, "POST", f"/api/public/companies/{slug}/session")
    if response.status_code != 200:
        raise CampaignFailure(f"session_status_{response.status_code}")
    payload = response.json()
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise CampaignFailure("session_token_missing")
    return token, payload, latency


async def _turn(client: httpx.AsyncClient, token: str, text: str) -> tuple[dict[str, Any], float]:
    response, latency = await _request(
        client,
        "POST",
        "/api/public/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": text, "client_message_id": f"closure-{uuid.uuid4().hex}"},
    )
    if response.status_code != 200:
        raise CampaignFailure(f"turn_status_{response.status_code}")
    payload = response.json()
    if payload.get("status") != "completed" or not payload.get("id"):
        raise CampaignFailure(f"turn_not_completed_{payload.get('status') or 'missing'}")
    return payload, latency


def _semantic_trace(payload: dict[str, Any], company_id: str) -> dict[str, Any]:
    """Read the compact, non-conversational trace persisted for one HTTP turn."""
    meta = ((payload.get("response") or {}).get("meta") or {})
    source_message_id = str(meta.get("source_message_id") or "")
    if not source_message_id.isdigit():
        raise CampaignFailure("semantic_trace_source_message_missing")
    db = SessionLocal()
    try:
        row = (
            db.query(SystemEvent)
            .filter(
                SystemEvent.company_id == company_id,
                SystemEvent.event_type == "telemetry.ai_response",
                SystemEvent.entity_id.like(f"%:{source_message_id}"),
            )
            .order_by(SystemEvent.id.desc())
            .first()
        )
        if not row:
            raise CampaignFailure("semantic_trace_missing")
        trace = (json.loads(row.payload).get("trace") or {}).get("semantic_fulfillment")
    finally:
        db.close()
    if not isinstance(trace, dict) or trace.get("schema") != "velor_semantic_fulfillment_trace_v1":
        raise CampaignFailure("semantic_trace_contract_missing")
    if trace.get("verifier_passed") is not True:
        raise CampaignFailure("semantic_fulfillment_verifier_failed")
    return trace


def _capability(payload: dict[str, Any]) -> str | None:
    return ((payload.get("response") or {}).get("meta") or {}).get("capability")


def _action_status(payload: dict[str, Any]) -> str | None:
    presentation = (payload.get("response") or {}).get("presentation") or {}
    action = presentation.get("conversation_action") or {}
    return action.get("status")


async def _keepalive_status(client: httpx.AsyncClient, cookies: dict[str, str]) -> bool:
    async with client.stream(
        "GET",
        "/api/v1/events/stream",
        headers={"Last-Event-ID": "999999999"},
        cookies=cookies,
    ) as response:
        if response.status_code != 200:
            return False
        iterator = response.aiter_lines()
        try:
            line = await asyncio.wait_for(anext(iterator), timeout=4.0)
        except TimeoutError:
            return False
        return line.startswith(": keepalive")


def _tenant_cookie(company_id: str, secret: str) -> dict[str, str]:
    return {
        "access_token": jwt.encode(
            {"company_id": company_id, "role": "tenant", "token_type": "access"},
            secret,
            algorithm="HS256",
        )
    }


async def _adversarial_campaign(clients: list[httpx.AsyncClient], slug: str, company_id: str) -> dict[str, Any]:
    capabilities: Counter[str] = Counter()
    obligations: Counter[str] = Counter()
    latencies: list[float] = []
    collision_outcomes: dict[str, str | None] = {}
    status_counts: Counter[str] = Counter()
    sanitized_turn_traces: list[dict[str, Any]] = []

    # Visitor-scoped sessions keep history bounded while staying within the
    # public limits. A session that executes an action is retired immediately;
    # this preserves the real paused/handoff safety behavior without letting it
    # mask a later independent adversarial turn.
    sessions: list[tuple[str, httpx.AsyncClient]] = []
    session_latencies: list[float] = []
    for index in range(CAMPAIGN_SESSION_POOL_SIZE):
        client = clients[index]
        token, _session, session_latency = await _new_session(client, slug)
        sessions.append((token, client))
        session_latencies.append(session_latency)
    sessions_created = len(sessions)
    latencies.extend(session_latencies)

    # The first 198 turns rotate through bounded visitor histories. The final
    # two validate a persisted offered action in an active session.
    for index in range(198):
        text = ADVERSARIAL_TURNS[index % len(ADVERSARIAL_TURNS)]
        token_slot = index % len(sessions)
        token, turn_client = sessions[token_slot]
        payload, turn_latency = await _turn(turn_client, token, text)
        semantic_trace = _semantic_trace(payload, company_id)
        latencies.append(turn_latency)
        status_counts["200"] += 1
        capability = _capability(payload)
        capabilities[str(capability)] += 1
        obligations[str(semantic_trace.get("obligation_type"))] += 1
        sanitized_turn_traces.append({"turn": index + 1, "semantic": semantic_trace})
        if text in EXPECTED_COLLISIONS:
            collision_outcomes[text] = capability
        if _action_status(payload) == "executed":
            replacement_token, _replacement_session, replacement_latency = await _new_session(turn_client, slug)
            sessions[token_slot] = (replacement_token, turn_client)
            sessions_created += 1
            latencies.append(replacement_latency)
        if index < 197:
            await asyncio.sleep(CAMPAIGN_TURN_INTERVAL_SECONDS)

    token, action_client = sessions[0]
    offer, offer_latency = await _turn(action_client, token, "فيه تقسيط؟")
    accept, accept_latency = await _turn(action_client, token, "اسأل الفريق")
    offer_trace = _semantic_trace(offer, company_id)
    accept_trace = _semantic_trace(accept, company_id)
    latencies.extend((offer_latency, accept_latency))
    status_counts["200"] += 2
    obligations[str(offer_trace.get("obligation_type"))] += 1
    obligations[str(accept_trace.get("obligation_type"))] += 1
    sanitized_turn_traces.extend((
        {"turn": 199, "semantic": offer_trace},
        {"turn": 200, "semantic": accept_trace},
    ))

    collision_ok = all(collision_outcomes.get(text) == expected for text, expected in EXPECTED_COLLISIONS.items())
    if _action_status(offer) != "offered" or _action_status(accept) != "executed":
        raise CampaignFailure("verification_action_not_persisted")
    if not collision_ok:
        raise CampaignFailure("collision_capability_mismatch")
    if len(sanitized_turn_traces) != 200:
        raise CampaignFailure("semantic_trace_count_mismatch")
    return {
        "turns": 200,
        "visitor_sessions_created": sessions_created,
        "active_visitor_sessions": CAMPAIGN_SESSION_POOL_SIZE,
        "source_ip_pool": len(CAMPAIGN_SOURCE_IPS),
        "status_counts": dict(status_counts),
        "capability_counts": dict(sorted(capabilities.items())),
        "obligation_counts": dict(sorted(obligations.items())),
        "collision_cases": len(EXPECTED_COLLISIONS),
        "collision_cases_passed": collision_ok,
        "verification_offer_then_accept": True,
        "semantic_fulfillment_passed": True,
        "sanitized_turn_traces": sanitized_turn_traces,
        "p95_ms": _p95(latencies),
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else None,
        "zero_5xx": True,
    }


async def _two_tenant_proof(client: httpx.AsyncClient, slug_a: str, slug_b: str, secret: str) -> dict[str, Any]:
    token_a, session_a, _ = await _new_session(client, slug_a)
    token_b, session_b, _ = await _new_session(client, slug_b)
    price_a, _ = await _turn(client, token_a, "Arvena Ergo One بكام؟")
    price_b, _ = await _turn(client, token_b, "Arvena Ergo One بكام؟")
    if "6900" not in str(price_a.get("reply")) or "7500" not in str(price_b.get("reply")):
        raise CampaignFailure("overlapping_product_price_not_isolated")

    offer_a, _ = await _turn(client, token_a, "فيه تقسيط؟")
    accept_a, _ = await _turn(client, token_a, "اسأل الفريق")
    offer_b, _ = await _turn(client, token_b, "فيه تقسيط؟")
    if _action_status(offer_a) != "offered" or _action_status(accept_a) != "executed" or _action_status(offer_b) != "offered":
        raise CampaignFailure("pending_action_scope_failure")

    handoff_a, _ = await _turn(client, token_a, "وصلني بخدمة العملاء")
    if _action_status(handoff_a) != "executed":
        raise CampaignFailure("handoff_not_executed")
    session_b_response, _ = await _request(
        client,
        "GET",
        f"/api/public/companies/{slug_b}/session",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    if session_b_response.status_code != 200 or session_b_response.json().get("is_paused"):
        raise CampaignFailure("handoff_cross_tenant_leak")

    # Administrative-surface access checks use API authentication only.  Lead
    # ids are read locally solely to construct cross-tenant API requests; they
    # are not emitted into the report.
    from database import Lead, SessionLocal

    db = SessionLocal()
    try:
        lead_a = db.query(Lead).filter(Lead.company_id == "velor_demo_arvena", Lead.external_customer_id == session_a["visitor_id"]).one()
        lead_b = db.query(Lead).filter(Lead.company_id == "velor_demo_baraka", Lead.external_customer_id == session_b["visitor_id"]).one()
        lead_a_id, lead_b_id = lead_a.id, lead_b.id
    finally:
        db.close()

    cookie_a = _tenant_cookie("velor_demo_arvena", secret)
    cookie_b = _tenant_cookie("velor_demo_baraka", secret)
    queue_a, _ = await _request(client, "GET", "/api/engine/queue", cookies=cookie_a)
    queue_b, _ = await _request(client, "GET", "/api/engine/queue", cookies=cookie_b)
    attention_a, _ = await _request(client, "GET", "/api/engine/attention", cookies=cookie_a)
    attention_b, _ = await _request(client, "GET", "/api/engine/attention", cookies=cookie_b)
    own_workspace, _ = await _request(client, "GET", f"/api/v1/crm/customers/{lead_b_id}/suggested-replies", cookies=cookie_b)
    cross_workspace, _ = await _request(client, "GET", f"/api/v1/crm/customers/{lead_b_id}/suggested-replies", cookies=cookie_a)
    cross_timeline, _ = await _request(client, "GET", f"/api/leads/{lead_b_id}/timeline", cookies=cookie_a)
    own_timeline, _ = await _request(client, "GET", f"/api/leads/{lead_b_id}/timeline", cookies=cookie_b)
    cross_copilot, _ = await _request(
        client,
        "POST",
        "/api/v1/copilot/chat",
        cookies=cookie_a,
        json={"message": "summarize this lead", "scope": "lead", "lead_id": lead_b_id},
    )
    own_copilot, _ = await _request(
        client,
        "POST",
        "/api/v1/copilot/chat",
        cookies=cookie_b,
        json={"message": "summarize this lead", "scope": "lead", "lead_id": lead_b_id},
    )
    sse_a, sse_b = await asyncio.gather(_keepalive_status(client, cookie_a), _keepalive_status(client, cookie_b))

    checks = {
        "state": True,
        "overlapping_product_policy": True,
        "pending_actions": True,
        "handoff": True,
        "queue": queue_a.status_code == queue_b.status_code == 200,
        "workspace_and_drafts": own_workspace.status_code == 200 and cross_workspace.status_code == 404,
        "lead_workspace": own_timeline.status_code == 200 and cross_timeline.status_code == 404,
        "ask_velor": own_copilot.status_code == 200 and cross_copilot.status_code == 404,
        "sse": sse_a and sse_b,
        "tenant_a_lead_lookup": lead_a_id != lead_b_id,
        "attention": attention_a.status_code == attention_b.status_code == 200,
    }
    if not all(checks.values()):
        raise CampaignFailure("two_tenant_surface_isolation_failure")
    return {"checks": checks, "passed": True}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    timeout = httpx.Timeout(args.timeout)
    async with AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=args.base_url.rstrip("/"),
                    timeout=timeout,
                    transport=httpx.AsyncHTTPTransport(local_address=source_ip),
                )
            )
            for source_ip in CAMPAIGN_SOURCE_IPS
        ]
        ready, _ = await _request(clients[0], "GET", "/ready")
        readiness = ready.json() if ready.status_code == 200 else {}
        if readiness.get("provider_available") is not False:
            raise CampaignFailure("provider_must_be_unavailable_for_campaign")
        adversarial = await _adversarial_campaign(clients, args.slug_a, args.company_id_a)
        isolation = await _two_tenant_proof(clients[0], args.slug_a, args.slug_b, args.jwt_secret)
    return {
        "schema_version": "velor_final_closure_campaign_v1",
        "mode": "real_route_fallback_only",
        "provider_available": False,
        "adversarial_runtime": adversarial,
        "two_tenant_api_proof": isolation,
        "passed": True,
        "privacy": {"tokens": False, "visitor_ids": False, "request_text": False, "response_prose": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--slug-a", default="arvena-demo")
    parser.add_argument("--slug-b", default="baraka-demo")
    parser.add_argument("--company-id-a", default="velor_demo_arvena")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--jwt-secret", default=os.getenv("JWT_SECRET", ""))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.jwt_secret:
        raise SystemExit("JWT secret is required")
    report = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
