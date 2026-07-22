import json
from collections import Counter

import httpx
import pytest

from scripts.pilot_load_test import (
    LoadConfig,
    PilotLoadHarness,
    RequestResult,
    build_report,
    latency_summary,
    percentile,
)


def _safe_readiness():
    return {
        "status": "degraded",
        "engine_version": "v2",
        "provider_available": False,
        "fallback_available": True,
    }


def _passing_probes():
    return {
        "idempotency": [
            RequestResult("probe_idempotency", 200, 10, reply_id="pub-repeat"),
            RequestResult("probe_idempotency", 200, 8, reply_id="pub-repeat", duplicate=True),
        ],
        "long_allowed": [RequestResult("probe_long_allowed", 200, 12, reply_id="pub-long")],
        "oversize": [RequestResult("probe_oversize", 400, 4)],
    }


def test_percentile_and_latency_summary_are_deterministic():
    assert percentile([], 50) is None
    assert percentile([7], 99) == 7
    assert percentile([0, 10, 20, 30], 50) == 15
    assert percentile([0, 10, 20, 30], 95) == 28.5
    assert percentile([0, 10, 20, 30], 99) == 29.7
    with pytest.raises(ValueError):
        percentile([1], 101)

    summary = latency_summary(
        [RequestResult("turn", 200, 10), RequestResult("turn", 200, 20)]
    )
    assert summary == {"count": 2, "p50_ms": 15.0, "p95_ms": 19.5, "p99_ms": 19.9, "max_ms": 20}


def test_report_and_all_pass_gates_for_supported_fallback_traffic():
    config = LoadConfig(visitors=1, turns_per_visitor=1, concurrency=1)
    report = build_report(
        config,
        _safe_readiness(),
        [RequestResult("session_init", 200, 20)],
        [RequestResult("turn", 200, 100, reply_id="pub-normal")],
        _passing_probes(),
        [],
    )

    assert report["passed"] is True
    assert all(report["gates"].values())
    assert report["statuses"]["4xx"] == 1  # expected oversize probe is still reported
    assert report["normal_traffic_4xx"] == 0
    assert report["probes"]["idempotency"]["same_reply_id"] is True
    assert report["privacy"] == {
        "tokens_in_report": False,
        "visitor_ids_in_report": False,
        "messages_in_report": False,
        "response_prose_in_report": False,
    }


def test_report_failure_gates_count_4xx_5xx_duplicates_latency_and_unhandled_errors():
    config = LoadConfig(
        visitors=1,
        turns_per_visitor=2,
        concurrency=1,
        max_session_p95_ms=10,
        max_turn_p95_ms=10,
    )
    report = build_report(
        config,
        _safe_readiness(),
        [RequestResult("session_init", 200, 20)],
        [
            RequestResult("turn", 429, 30, reply_id="duplicate-id"),
            RequestResult("turn", 500, 40, reply_id="duplicate-id"),
        ],
        _passing_probes(),
        ["ConnectTimeout"],
    )

    assert report["passed"] is False
    assert report["statuses"]["4xx"] == 2  # normal 429 + expected oversize 400
    assert report["statuses"]["5xx"] == 1
    assert report["normal_traffic_4xx"] == 1
    assert report["duplicate_normal_reply_ids"] == ["duplicate-id"]
    assert report["unhandled_error_categories"] == {"ConnectTimeout": 1}
    assert report["gates"]["no_unexpected_4xx"] is False
    assert report["gates"]["no_5xx"] is False
    assert report["gates"]["no_duplicate_normal_reply_ids"] is False
    assert report["gates"]["session_p95_within_target"] is False
    assert report["gates"]["turn_p95_within_target"] is False


@pytest.mark.asyncio
async def test_harness_refuses_load_when_external_provider_is_available():
    calls = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        calls[request.url.path] += 1
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "engine_version": "v2",
                    "provider_available": True,
                    "fallback_available": True,
                },
            )
        return httpx.Response(500)

    harness = PilotLoadHarness(
        LoadConfig(visitors=2, turns_per_visitor=2, concurrency=2),
        transport=httpx.MockTransport(handler),
    )
    report = await harness.run()

    assert report["aborted_for_provider_safety"] is True
    assert report["passed"] is False
    assert report["gates"]["fallback_only_safety"] is False
    assert calls == {"/ready": 1}


@pytest.mark.asyncio
async def test_stub_transport_runs_sessions_turns_idempotency_long_and_oversize_without_sensitive_report_data():
    issued_sessions = 0
    replies_by_client_message_id = {}
    chat_lengths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal issued_sessions
        if request.url.path == "/ready":
            return httpx.Response(200, json=_safe_readiness())
        if request.url.path.endswith("/session") and request.method == "POST":
            issued_sessions += 1
            return httpx.Response(
                200,
                json={
                    "token": f"secret-token-{issued_sessions}",
                    "visitor_id": f"secret-visitor-{issued_sessions}",
                    "company_name": "Test",
                },
            )
        if request.url.path == "/api/public/chat" and request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            message = body["message"]
            client_message_id = body["client_message_id"]
            chat_lengths.append(len(message))
            if len(message) > 1000:
                return httpx.Response(400, json={"detail": "too long"})
            if client_message_id in replies_by_client_message_id:
                return httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "reply": "redacted reply body",
                        "id": replies_by_client_message_id[client_message_id],
                        "duplicate": True,
                    },
                )
            reply_id = f"pub-{len(replies_by_client_message_id) + 1}"
            replies_by_client_message_id[client_message_id] = reply_id
            return httpx.Response(
                200,
                json={"status": "completed", "reply": "redacted reply body", "id": reply_id},
            )
        return httpx.Response(404)

    config = LoadConfig(
        base_url="https://stub.invalid",
        visitors=3,
        turns_per_visitor=2,
        concurrency=2,
        max_session_p95_ms=1000,
        max_turn_p95_ms=1000,
    )
    report = await PilotLoadHarness(config, transport=httpx.MockTransport(handler)).run()
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["passed"] is True
    assert report["latency"]["session_init"]["count"] == 3
    assert report["latency"]["turns"]["count"] == 6
    assert report["probes"]["idempotency"]["same_reply_id"] is True
    assert report["probes"]["long_allowed"]["status"] == 200
    assert report["probes"]["oversize_rejection"]["status"] == 400
    assert 900 in chat_lengths
    assert 1001 in chat_lengths
    assert issued_sessions == 6  # three probes plus three load visitors
    assert "secret-token" not in rendered
    assert "secret-visitor" not in rendered
    assert "redacted reply body" not in rendered
    assert "عندكم كراسي" not in rendered


def test_config_rejects_unsafe_probe_lengths():
    with pytest.raises(ValueError):
        PilotLoadHarness(LoadConfig(long_allowed_length=1001))
    with pytest.raises(ValueError):
        PilotLoadHarness(LoadConfig(oversize_length=1000))
