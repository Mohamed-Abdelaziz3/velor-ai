"""
workers/rq_client.py — Shared RQ queue client
==============================================
Issue #9 — singleton Redis connection + queue for brain.py to enqueue jobs.

Falls back to direct (synchronous) call if Redis is unavailable,
preserving the old behaviour without crashing.
"""

import logging
import os

log = logging.getLogger("adam.rq_client")

_queue = None
_rq_available = True


def _get_queue():
    global _queue, _rq_available
    if not _rq_available:
        return None
    if _queue is not None:
        return _queue
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        from rq import Queue

        conn = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        conn.ping()
        _queue = Queue("adam-sheets", connection=conn)
        log.info("✅ RQ queue 'adam-sheets' connected")
        return _queue
    except Exception as exc:
        log.warning("⚠️  RQ unavailable (%s) — Sheets sync will run inline (unreliable)", exc)
        _rq_available = False
        return None


def enqueue_sheets_log(name: str, phone: str, interest: str, company_id: str = "default", allow_inline: bool = False) -> None:
    """
    Enqueue a Google Sheets sync job.
    - Redis available  →  enqueued (reliable, retried on failure)
    - Redis missing    →  synchronous fallback (old behaviour)
    """
    q = _get_queue()
    if q is not None:
        try:
            q.enqueue(
                "workers.sheets_worker.sync_lead_to_sheets",
                name,
                phone,
                interest,
                company_id,
                retry=3,
                job_timeout=30,
            )
            return
        except Exception as exc:
            log.warning("RQ enqueue failed — falling back to direct call: %s", exc)

    if not allow_inline:
        log.warning("Sheets sync skipped because RQ/Redis is unavailable")
        return

    # Fallback: direct sync call, only for maintenance scripts.
    try:
        from workers.sheets_worker import sync_lead_to_sheets

        sync_lead_to_sheets(name, phone, interest, company_id)
    except Exception as exc:
        log.error("Direct Sheets sync also failed: %s", exc)
