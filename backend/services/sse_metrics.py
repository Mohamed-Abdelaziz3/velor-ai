"""
services/sse_metrics.py — Cached Dashboard Metrics for SSE
============================================================
Performance fix: Instead of running ~30 DB queries every 2 seconds per
connected dashboard client, we cache the heavy aggregate metrics with a
TTL. Only the lightweight lead-diff query runs on every SSE tick.

Cache is per-company_id with a configurable TTL (default 15 seconds).
"""

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

log = logging.getLogger("adam.sse_metrics")

# ── In-memory TTL cache ──────────────────────────────
_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 15  # Recompute at most every 15 seconds per company
_MAX_CACHE_ENTRIES = int(os.getenv("ADAM_SSE_CACHE_MAX_ENTRIES", "500"))


def _is_cache_valid(company_id: str) -> bool:
    entry = _cache.get(company_id)
    if not entry:
        return False
    age = (datetime.now(timezone.utc) - entry["_ts"]).total_seconds()
    return age < _CACHE_TTL_SECONDS


def get_cached_metrics(company_id: str) -> Optional[Dict[str, Any]]:
    """Return cached metrics if still valid, else None."""
    with _cache_lock:
        if _is_cache_valid(company_id):
            return _cache[company_id]["data"]
    return None


def invalidate_metrics_cache(company_id: str) -> None:
    """Clear cached dashboard metrics after company-scoped writes."""
    with _cache_lock:
        _cache.pop(company_id, None)


def compute_and_cache_metrics(db: Session, company_id: str) -> Dict[str, Any]:
    """
    Compute all heavy dashboard aggregate metrics and cache them.
    Returns the computed metrics dict.
    """
    # Check cache first (another thread may have just computed it)
    cached = get_cached_metrics(company_id)
    if cached is not None:
        return cached

    from database import (
        Lead,
        Message,
        Company,
        Notification,
        FollowUpTask,
        get_live_leads_filter,
        get_active_leads_query,
        get_hot_leads_query,
        get_urgent_intervention_query,
    )

    live_leads_filter = get_live_leads_filter(Lead)

    # Synthetic fixtures use the same Message table as real traffic. Exclude
    # messages whose scoped channel identifier belongs to a test lead so a
    # demo seed can never inflate merchant-facing operational counts.
    test_identifier_rows = db.query(
        Lead.external_customer_id,
        Lead.whatsapp_number,
        Lead.phone,
        Lead.whatsapp_jid,
    ).filter(
        Lead.company_id == company_id,
        Lead.is_deleted == False,
        Lead.is_test == True,
    ).all()
    test_identifiers = sorted({
        str(identifier)
        for row in test_identifier_rows
        for identifier in row
        if identifier
    })
    live_message_filters = [
        Message.company_id == company_id,
        Message.is_deleted == False,
    ]
    if test_identifiers:
        live_message_filters.append(Message.user_id.notin_(test_identifiers))

    # ── Basic counts ──
    # Dashboard counts are read from the canonical tables. ``UsageStats`` is an
    # enforcement counter and historically missed several Web Chat write paths;
    # presenting it as observed workspace volume made real rows disappear from
    # the UI. The aggregate is cached below, so correctness does not require a
    # counter shortcut here.
    l_count = get_active_leads_query(db, company_id).count()
    c_count = db.query(Message).filter(*live_message_filters).count()

    # ── Automation rate (all-time) ──
    total_bot_msgs = db.query(Message).filter(
        *live_message_filters,
        Message.sender == "assistant",
    ).count()
    total_human_msgs = db.query(Message).filter(
        *live_message_filters,
        Message.sender == "owner",
    ).count()
    total_all_messages = total_bot_msgs + total_human_msgs
    automation_rate = int((total_bot_msgs / total_all_messages) * 100) if total_all_messages > 0 else None
    hours_saved = round((total_bot_msgs * 20) / 3600, 1)

    # ── Timeframe metrics ──
    now_utc = datetime.now(timezone.utc)
    workspace_tz = ZoneInfo("Africa/Cairo")
    today_start = now_utc.astimezone(workspace_tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    timeframes = {
        "اليوم": today_start,
        "آخر 7 أيام": now_utc - timedelta(days=7),
        "آخر 30 يومًا": now_utc - timedelta(days=30),
    }

    ai_metrics = {}
    for tf_key, tf_start in timeframes.items():
        l_count_tf = get_active_leads_query(db, company_id).filter(Lead.created_at >= tf_start).count()
        h_count_tf = get_hot_leads_query(db, company_id).filter(Lead.created_at >= tf_start).count()

        bot_msgs_tf = (
            db.query(Message).filter(
                *live_message_filters,
                Message.sender == "assistant",
                Message.created_at >= tf_start,
            ).count()
        )
        human_msgs_tf = db.query(Message).filter(
            *live_message_filters,
            Message.sender == "owner",
            Message.created_at >= tf_start,
        ).count()
        all_msgs_tf = bot_msgs_tf + human_msgs_tf

        auto_rate_tf = int((bot_msgs_tf / all_msgs_tf) * 100) if all_msgs_tf > 0 else None
        hours_saved_tf = round((bot_msgs_tf * 20) / 3600, 1)

        # A mutable Lead.updated_at timestamp cannot prove that a sale happened
        # inside this window. Keep the compatibility field explicitly unknown
        # until an immutable CONFIRMED_ORDER/PAID event owns this metric.
        won_deals_tf = None
        pending_deals_tf = (
            db.query(Lead)
            .filter(
                Lead.company_id == company_id,
                Lead.is_deleted == False,
                live_leads_filter,
                Lead.status.in_(["qualified", "فرصة واعدة"]),
                Lead.updated_at >= tf_start,
            )
            .count()
        )
        critical_deals_tf = (
            db.query(Lead)
            .filter(
                Lead.company_id == company_id,
                Lead.is_deleted == False,
                live_leads_filter,
                Lead.status.in_(["angry", "محتاج تدخل / غاضب 🚨"]),
                Lead.updated_at >= tf_start,
            )
            .count()
        )

        ai_metrics[tf_key] = {
            "leads": l_count_tf,
            "hot": h_count_tf,
            "automation_rate": auto_rate_tf,
            "hours_saved": hours_saved_tf,
            "won_deals": won_deals_tf,
            "pending_deals": pending_deals_tf,
            "critical_deals": critical_deals_tf,
        }

    # ── Urgent leads + NBA ──
    two_hours_ago = now_utc - timedelta(hours=2)
    urgent_leads_count = get_urgent_intervention_query(db, company_id).filter(Lead.last_contact_date < two_hours_ago).count()

    nba_leads = get_urgent_intervention_query(db, company_id).order_by(Lead.updated_at.desc()).limit(3).all()
    next_best_actions = []
    for lead in nba_leads:
        action_text = "🤖 خطوة مقترحة: راجع آخر رسائل العميل لفهم احتياجه."
        if lead.status in ["محتاج تدخل / غاضب 🚨", "angry"] or lead.needs_human_intervention:
            action_text = "🤖 خطوة مقترحة: العميل منزعج أو يحتاج لتدخل بشري فوري، راجع الشات الآن."
        elif lead.status in ["شراء مؤكد", "اهتمام عالي", "qualified", "فرصة واعدة"] or lead.is_hot_deal:
            action_text = "🤖 خطوة مقترحة: العميل سأل عن التفاصيل أو مهتم جداً، اتصل به الآن لحسم الصفقة."

        next_best_actions.append(
            {
                "lead_id": lead.id,
                "phone": lead.whatsapp_number or lead.phone,
                "contact_identifier": (
                    lead.external_customer_id
                    if lead.channel_type == "VELOR_WEB_CHAT"
                    else (lead.whatsapp_number or lead.phone or lead.whatsapp_jid)
                ),
                "channel_type": lead.channel_type or "WHATSAPP_QR",
                "customer_provided_phone": lead.customer_provided_phone,
                "name": lead.name,
                "status": lead.status,
                "is_hot_deal": lead.is_hot_deal,
                "action": action_text,
            }
        )

    # ── Daily target ──
    company = db.query(Company).filter(Company.company_id == company_id).first()
    daily_target = company.daily_sales_target if company else 5
    won_deals_today = None

    # ── Notifications scan ──
    overdue_tasks = (
        db.query(FollowUpTask)
        .join(Lead, FollowUpTask.lead_id == Lead.id)
        .filter(
            FollowUpTask.status == "pending",
            FollowUpTask.due_at < now_utc,
            Lead.company_id == company_id,
            Lead.is_test == False,
            Lead.stage.notin_(["Won", "Lost"]),
        )
        .all()
    )
    for task in overdue_tasks:
        existing_notif = (
            db.query(Notification)
            .filter(
                Notification.company_id == company_id,
                Notification.lead_id == task.lead_id,
                Notification.type == "overdue_followup",
                Notification.read_at.is_(None),
            )
            .first()
        )
        if not existing_notif:
            db.add(
                Notification(
                    company_id=company_id,
                    lead_id=task.lead_id,
                    type="overdue_followup",
                    title="⏰ Follow-Up Overdue",
                    message=f"Task requires action for lead #{task.lead_id}",
                )
            )
            db.commit()

    unread_notifs_count = (
        db.query(Notification)
        .filter(
            Notification.company_id == company_id,
            Notification.read_at.is_(None),
        )
        .count()
    )

    result = {
        "total_leads": l_count,
        "total_conversations": c_count,
        "automation_rate": automation_rate,
        "hours_saved": hours_saved,
        "ai_metrics": ai_metrics,
        "urgent_leads_count": urgent_leads_count,
        "next_best_actions": next_best_actions,
        "daily_target": daily_target,
        "won_deals_today": won_deals_today,
        "notifications_unread_count": unread_notifs_count,
        "has_new_notification": unread_notifs_count > 0,
        "metrics_meta": {
            "as_of": now_utc.isoformat().replace("+00:00", "Z"),
            "timezone": "Africa/Cairo",
            "total_leads": {
                "definition": "non-terminal, non-test leads in the canonical leads table",
                "source": "leads",
            },
            "total_conversations": {
                "definition": "persisted, non-deleted message rows (compatibility key)",
                "source": "messages",
                "unit": "messages",
            },
            "automation_rate": {
                "definition": "assistant replies / (assistant replies + owner replies)",
                "source": "messages.sender",
                "window": "all_time",
            },
            "hours_saved": {
                "definition": "assistant replies × 20 seconds",
                "source": "estimate",
                "assumption_seconds_per_reply": 20,
            },
            "won_deals_today": {
                "status": "not_measured",
                "reason": "No immutable trusted order or payment event is connected.",
            },
        },
    }

    # Store in cache with bounded size and simple FIFO eviction
    with _cache_lock:
        if len(_cache) >= _MAX_CACHE_ENTRIES and company_id not in _cache:
            # Evict the oldest entry by timestamp
            oldest = min(_cache.items(), key=lambda kv: kv[1]["_ts"])[0]
            try:
                del _cache[oldest]
            except KeyError:
                pass
        _cache[company_id] = {"data": result, "_ts": datetime.now(timezone.utc)}

    log.debug("Recomputed SSE metrics for %s (%d queries cached for %ds)", company_id, 30, _CACHE_TTL_SECONDS)
    return result
