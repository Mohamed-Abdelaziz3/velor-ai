"""Pilot-scale asynchronous load and failure harness for Public Web Chat.

The harness refuses to send load when `/ready` reports an available external
provider.  This keeps the default 25 x 10 run on the deterministic/fallback
path and prevents accidental paid-provider traffic.

Reports never contain visitor tokens, visitor identifiers, request messages,
or response prose.  They contain only aggregate timings, status classes,
opaque public reply identifiers, and sanitized error categories.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx


TURN_MESSAGES = (
    "عندكم كراسي مكتب؟",
    "أنا عايز اللي بـ6900",
    "عايز أعرف تفاصيل عنه",
    "السعر غالي أوي",
    "أنا معايا 7000 جنيه",
    "إيه الفرق بين Ergo One وErgo Pro؟",
    "استخدامي 8 ساعات",
    "الضمان 10 سنين؟",
    "متوفر دلوقتي؟",
    "تمام هاخد Ergo One، أعمل إيه؟",
)


@dataclass(frozen=True)
class LoadConfig:
    base_url: str = "http://127.0.0.1:8000"
    public_slug: str = "arvena-demo"
    visitors: int = 25
    turns_per_visitor: int = 10
    concurrency: int = 25
    timeout_seconds: float = 60.0
    long_allowed_length: int = 900
    oversize_length: int = 1001
    max_session_p95_ms: float = 2000.0
    max_turn_p95_ms: float = 5000.0

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequestResult:
    phase: str
    status_code: int | None
    latency_ms: float
    reply_id: str | None = None
    duplicate: bool = False
    error_category: str | None = None


def percentile(values: Sequence[float], percentile_value: float) -> float | None:
    """Return a deterministic linearly interpolated percentile."""
    if not values:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * (percentile_value / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 3)


def latency_summary(results: Sequence[RequestResult]) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    return {
        "count": len(latencies),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "max_ms": round(max(latencies), 3) if latencies else None,
    }


def _status_summary(results: Sequence[RequestResult]) -> dict[str, Any]:
    counts = Counter(str(result.status_code) if result.status_code is not None else "transport_error" for result in results)
    return {
        "by_status": dict(sorted(counts.items())),
        "2xx": sum(1 for result in results if result.status_code is not None and 200 <= result.status_code < 300),
        "4xx": sum(1 for result in results if result.status_code is not None and 400 <= result.status_code < 500),
        "5xx": sum(1 for result in results if result.status_code is not None and 500 <= result.status_code < 600),
        "transport_errors": sum(result.status_code is None for result in results),
    }


def _unexpected_duplicate_reply_ids(results: Sequence[RequestResult]) -> list[str]:
    ids = [result.reply_id for result in results if result.reply_id]
    return sorted(reply_id for reply_id, count in Counter(ids).items() if count > 1)


def _probe_summary(probes: Mapping[str, Sequence[RequestResult]]) -> dict[str, Any]:
    idempotency = list(probes.get("idempotency", []))
    long_allowed = list(probes.get("long_allowed", []))
    oversize = list(probes.get("oversize", []))
    same_reply_id = bool(
        len(idempotency) == 2
        and idempotency[0].reply_id
        and idempotency[0].reply_id == idempotency[1].reply_id
        and idempotency[1].duplicate
    )
    return {
        "idempotency": {
            "statuses": [result.status_code for result in idempotency],
            "same_reply_id": same_reply_id,
            "duplicate_flag": bool(len(idempotency) == 2 and idempotency[1].duplicate),
        },
        "long_allowed": {
            "status": long_allowed[0].status_code if long_allowed else None,
            "length": None,  # message contents and text-derived details are deliberately omitted
        },
        "oversize_rejection": {
            "status": oversize[0].status_code if oversize else None,
            "length": None,
        },
    }


def build_report(
    config: LoadConfig,
    readiness: Mapping[str, Any],
    session_results: Sequence[RequestResult],
    turn_results: Sequence[RequestResult],
    probes: Mapping[str, Sequence[RequestResult]],
    unhandled_errors: Sequence[str],
    *,
    aborted_for_provider_safety: bool = False,
) -> dict[str, Any]:
    probe_results = [result for rows in probes.values() for result in rows]
    all_results = [*session_results, *turn_results, *probe_results]
    probe_summary = _probe_summary(probes)
    session_latency = latency_summary(session_results)
    turn_latency = latency_summary(turn_results)
    normal_results = [*session_results, *turn_results]
    normal_4xx = sum(result.status_code is not None and 400 <= result.status_code < 500 for result in normal_results)
    provider_safe = bool(
        readiness.get("engine_version") == "v2"
        and readiness.get("provider_available") is False
        and readiness.get("fallback_available") is True
        and not aborted_for_provider_safety
    )
    expected_sessions = config.visitors
    expected_turns = config.visitors * config.turns_per_visitor
    oversize_status = probe_summary["oversize_rejection"]["status"]
    long_status = probe_summary["long_allowed"]["status"]
    gates = {
        "fallback_only_safety": provider_safe,
        "all_sessions_completed": len(session_results) == expected_sessions
        and all(result.status_code is not None and 200 <= result.status_code < 300 for result in session_results),
        "all_turns_completed": len(turn_results) == expected_turns
        and all(result.status_code is not None and 200 <= result.status_code < 300 for result in turn_results),
        "no_unexpected_4xx": normal_4xx == 0,
        "no_5xx": all(not (result.status_code is not None and 500 <= result.status_code < 600) for result in all_results),
        "no_unhandled_errors": not unhandled_errors,
        "no_duplicate_normal_reply_ids": not _unexpected_duplicate_reply_ids(turn_results),
        "idempotency_reuses_reply": probe_summary["idempotency"]["same_reply_id"],
        "long_allowed_accepted": long_status is not None and 200 <= long_status < 300,
        "oversize_rejected": oversize_status in {400, 413, 422},
        "session_p95_within_target": session_latency["p95_ms"] is not None
        and session_latency["p95_ms"] <= config.max_session_p95_ms,
        "turn_p95_within_target": turn_latency["p95_ms"] is not None
        and turn_latency["p95_ms"] <= config.max_turn_p95_ms,
    }
    return {
        "schema_version": "velor_pilot_load_v1",
        "mode": "fallback_only_public_http",
        "config": config.public_dict(),
        "readiness": {
            "status": readiness.get("status"),
            "engine_version": readiness.get("engine_version"),
            "provider_available": readiness.get("provider_available"),
            "fallback_available": readiness.get("fallback_available"),
        },
        "aborted_for_provider_safety": aborted_for_provider_safety,
        "latency": {"session_init": session_latency, "turns": turn_latency},
        "statuses": _status_summary(all_results),
        "normal_traffic_4xx": normal_4xx,
        "duplicate_normal_reply_ids": _unexpected_duplicate_reply_ids(turn_results),
        "unhandled_error_count": len(unhandled_errors),
        "unhandled_error_categories": dict(sorted(Counter(unhandled_errors).items())),
        "probes": probe_summary,
        "gates": gates,
        "passed": all(gates.values()),
        "privacy": {
            "tokens_in_report": False,
            "visitor_ids_in_report": False,
            "messages_in_report": False,
            "response_prose_in_report": False,
        },
    }


class PilotLoadHarness:
    def __init__(self, config: LoadConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        if config.visitors < 1 or config.turns_per_visitor < 1 or config.concurrency < 1:
            raise ValueError("visitors, turns_per_visitor, and concurrency must be positive")
        if not 1 <= config.long_allowed_length <= 1000:
            raise ValueError("long_allowed_length must be between 1 and 1000")
        if config.oversize_length <= 1000:
            raise ValueError("oversize_length must be greater than 1000")
        self.config = config
        self.transport = transport
        self.run_id = uuid.uuid4().hex[:12]
        self._unhandled_errors: list[str] = []

    async def _request(
        self,
        client: httpx.AsyncClient,
        phase: str,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[RequestResult, dict[str, Any]]:
        started = time.perf_counter()
        try:
            response = await client.request(method, url, **kwargs)
            latency_ms = (time.perf_counter() - started) * 1000
            try:
                payload = response.json()
                if not isinstance(payload, dict):
                    payload = {}
            except (ValueError, json.JSONDecodeError):
                payload = {}
            result = RequestResult(
                phase=phase,
                status_code=response.status_code,
                latency_ms=round(latency_ms, 3),
                reply_id=str(payload.get("id")) if payload.get("id") else None,
                duplicate=payload.get("duplicate") is True,
                error_category=None if response.status_code < 400 else f"http_{response.status_code // 100}xx",
            )
            return result, payload
        except Exception as exc:  # transport failures are reportable, not allowed to crash the run
            latency_ms = (time.perf_counter() - started) * 1000
            category = exc.__class__.__name__
            self._unhandled_errors.append(category)
            return RequestResult(phase, None, round(latency_ms, 3), error_category=category), {}

    async def _readiness(self, client: httpx.AsyncClient) -> dict[str, Any]:
        result, payload = await self._request(client, "readiness", "GET", "/ready")
        if result.status_code is None:
            return {"status": "unreachable"}
        return {
            "status": payload.get("status"),
            "engine_version": payload.get("engine_version"),
            "provider_available": payload.get("provider_available"),
            "fallback_available": payload.get("fallback_available"),
        }

    async def _init_session(
        self, client: httpx.AsyncClient, phase: str = "session_init"
    ) -> tuple[RequestResult, str | None]:
        result, payload = await self._request(
            client,
            phase,
            "POST",
            f"/api/public/companies/{self.config.public_slug}/session",
        )
        token = payload.get("token") if result.status_code is not None and 200 <= result.status_code < 300 else None
        return result, str(token) if token else None

    async def _chat(
        self,
        client: httpx.AsyncClient,
        token: str,
        message: str,
        client_message_id: str,
        phase: str,
    ) -> RequestResult:
        result, _ = await self._request(
            client,
            phase,
            "POST",
            "/api/public/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message, "client_message_id": client_message_id},
        )
        return result

    async def _visitor_flow(
        self, client: httpx.AsyncClient, visitor_index: int, semaphore: asyncio.Semaphore
    ) -> tuple[RequestResult, list[RequestResult]]:
        async with semaphore:
            session_result, token = await self._init_session(client)
            turns: list[RequestResult] = []
            if not token:
                return session_result, turns
            for turn_index in range(self.config.turns_per_visitor):
                message = TURN_MESSAGES[turn_index % len(TURN_MESSAGES)]
                client_message_id = f"load-{self.run_id}-{visitor_index}-{turn_index}-{uuid.uuid4().hex}"
                turns.append(await self._chat(client, token, message, client_message_id, "turn"))
            return session_result, turns

    async def _run_probes(self, client: httpx.AsyncClient) -> dict[str, list[RequestResult]]:
        probes: dict[str, list[RequestResult]] = {"idempotency": [], "long_allowed": [], "oversize": []}

        _, token = await self._init_session(client, "probe_session")
        if token:
            repeated_id = f"probe-idempotency-{self.run_id}-{uuid.uuid4().hex}"
            for _ in range(2):
                probes["idempotency"].append(
                    await self._chat(client, token, "سعر Ergo One كام؟", repeated_id, "probe_idempotency")
                )

        _, token = await self._init_session(client, "probe_session")
        if token:
            long_message = "م" * self.config.long_allowed_length
            probes["long_allowed"].append(
                await self._chat(
                    client,
                    token,
                    long_message,
                    f"probe-long-{self.run_id}-{uuid.uuid4().hex}",
                    "probe_long_allowed",
                )
            )

        _, token = await self._init_session(client, "probe_session")
        if token:
            oversize_message = "م" * self.config.oversize_length
            probes["oversize"].append(
                await self._chat(
                    client,
                    token,
                    oversize_message,
                    f"probe-oversize-{self.run_id}-{uuid.uuid4().hex}",
                    "probe_oversize",
                )
            )
        return probes

    async def run(self) -> dict[str, Any]:
        timeout = httpx.Timeout(self.config.timeout_seconds)
        async with httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            timeout=timeout,
            transport=self.transport,
            headers={"User-Agent": "VELOR-Pilot-Load-Harness/1.0"},
        ) as client:
            readiness = await self._readiness(client)
            provider_safe = bool(
                readiness.get("engine_version") == "v2"
                and readiness.get("provider_available") is False
                and readiness.get("fallback_available") is True
            )
            if not provider_safe:
                return build_report(
                    self.config,
                    readiness,
                    [],
                    [],
                    {},
                    self._unhandled_errors,
                    aborted_for_provider_safety=True,
                )

            probes = await self._run_probes(client)
            semaphore = asyncio.Semaphore(self.config.concurrency)
            flows = await asyncio.gather(
                *(self._visitor_flow(client, index, semaphore) for index in range(self.config.visitors))
            )
            session_results = [session for session, _ in flows]
            turn_results = [turn for _, turns in flows for turn in turns]
            return build_report(
                self.config,
                readiness,
                session_results,
                turn_results,
                probes,
                self._unhandled_errors,
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fallback-only VELOR pilot HTTP load")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--public-slug", default="arvena-demo")
    parser.add_argument("--visitors", type=int, default=25)
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-session-p95-ms", type=float, default=2000.0)
    parser.add_argument("--max-turn-p95-ms", type=float, default=5000.0)
    parser.add_argument("--output", type=Path)
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    config = LoadConfig(
        base_url=args.base_url,
        public_slug=args.public_slug,
        visitors=args.visitors,
        turns_per_visitor=args.turns,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout,
        max_session_p95_ms=args.max_session_p95_ms,
        max_turn_p95_ms=args.max_turn_p95_ms,
    )
    report = await PilotLoadHarness(config).run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


def main() -> int:
    return asyncio.run(_main_async(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
