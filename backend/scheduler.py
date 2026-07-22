"""
scheduler.py — Background cleanup jobs
========================================
Issues #3 (expired token cleanup) and #4 (audit log retention).

Uses APScheduler. Started automatically when the FastAPI app starts
via the lifespan context manager in main.py.

Jobs:
  - Every day at 02:00 UTC  →  delete expired/revoked refresh tokens
  - Every day at 02:30 UTC  →  delete audit logs older than 90 days
"""

import logging
from functools import wraps

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from database import (
    SessionLocal,
    cleanup_expired_tokens,
    cleanup_old_audit_logs,
    engine,
    fail_pending_messages,
)

log = logging.getLogger("adam.scheduler")

_scheduler: BackgroundScheduler | None = None


def _cluster_singleton(lock_key: int):
    """Run a scheduled job once across all PostgreSQL web workers.

    APScheduler is process-local. A session-level advisory lock keeps duplicate
    workers from executing the same maintenance job concurrently. SQLite is
    restricted to development/test and keeps the existing single-process path.
    """

    def decorator(job):
        @wraps(job)
        def wrapped():
            connection = None
            acquired = True
            try:
                if engine.dialect.name == "postgresql":
                    connection = engine.connect()
                    acquired = bool(
                        connection.execute(
                            text("SELECT pg_try_advisory_lock(:lock_key)"),
                            {"lock_key": lock_key},
                        ).scalar()
                    )
                    if not acquired:
                        log.debug("Scheduler: skipped %s; cluster lock is held", job.__name__)
                        return None
                return job()
            finally:
                if connection is not None:
                    try:
                        if acquired:
                            connection.execute(
                                text("SELECT pg_advisory_unlock(:lock_key)"),
                                {"lock_key": lock_key},
                            )
                    finally:
                        connection.close()

        return wrapped

    return decorator


@_cluster_singleton(8_640_001)
def _job_cleanup_tokens() -> None:
    db = SessionLocal()
    try:
        n = cleanup_expired_tokens(db)
        log.info("Scheduler: cleaned %d expired tokens", n)
    finally:
        db.close()


@_cluster_singleton(8_640_002)
def _job_cleanup_audit_logs() -> None:
    db = SessionLocal()
    try:
        n = cleanup_old_audit_logs(db, retention_days=90)
        log.info("Scheduler: cleaned %d old audit logs", n)
    finally:
        db.close()


@_cluster_singleton(8_640_003)
def _job_fail_pending_messages() -> None:
    db = SessionLocal()
    try:
        n = fail_pending_messages(db, minutes_old=5)
        if n > 0:
            log.info("Scheduler: failed %d stuck pending messages", n)
    finally:
        db.close()


@_cluster_singleton(8_640_004)
def _job_recover_webhook_inbox() -> None:
    try:
        from routers.webhook import recover_pending_webhook_inbox

        recovered = recover_pending_webhook_inbox(limit=50)
        if recovered:
            log.info(
                "Scheduler: recovered %d durable webhook inbox items",
                recovered,
            )
    except Exception as exc:
        log.error(
            "Webhook inbox recovery failed category=%s",
            exc.__class__.__name__,
        )


@_cluster_singleton(8_640_005)
def _job_follow_up_sweeper() -> None:
    """Enforce evidence-bound owner-attention tasks for every active tenant."""
    from database import Company
    from services.follow_up_service import sync_follow_ups_from_attention

    db = SessionLocal()
    try:
        companies = db.query(Company.company_id).filter(Company.is_deleted == False).all()
        for (company_id,) in companies:
            try:
                created = sync_follow_ups_from_attention(db, company_id)
                if created:
                    log.info("Created %d evidence-bound follow-ups for tenant %s", created, company_id)
            except Exception as exc:
                db.rollback()
                log.error("Follow-up sweep failed tenant=%s category=%s", company_id, exc.__class__.__name__)
    except Exception as e:
        db.rollback()
        log.error("Follow-up sweeper failed category=%s", e.__class__.__name__)
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")

    # #3 — daily at 02:00 UTC
    _scheduler.add_job(
        _job_cleanup_tokens,
        trigger=CronTrigger(hour=2, minute=0),
        id="cleanup_tokens",
        replace_existing=True,
    )

    # #4 — daily at 02:30 UTC
    _scheduler.add_job(
        _job_cleanup_audit_logs,
        trigger=CronTrigger(hour=2, minute=30),
        id="cleanup_audit_logs",
        replace_existing=True,
    )

    # Fail pending messages — every 1 minute
    _scheduler.add_job(
        _job_fail_pending_messages,
        trigger=IntervalTrigger(minutes=1),
        id="fail_pending_messages",
        replace_existing=True,
    )

    _scheduler.add_job(
        _job_recover_webhook_inbox,
        trigger=IntervalTrigger(minutes=1),
        id="recover_webhook_inbox",
        replace_existing=True,
    )

    # Follow-Up Engine Sweeper — every 15 minutes
    _scheduler.add_job(
        _job_follow_up_sweeper,
        trigger=IntervalTrigger(minutes=15),
        id="follow_up_sweeper",
        replace_existing=True,
    )

    _scheduler.start()
    log.info("✅ Scheduler started (token cleanup @ 02:00, audit cleanup @ 02:30 UTC)")


def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("🛑 Scheduler stopped")
