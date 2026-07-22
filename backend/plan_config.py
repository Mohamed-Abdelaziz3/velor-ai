"""
plan_config.py — Plan definitions and enforcement helpers
=========================================================
Issue #6 — FREE / PRO / ENTERPRISE limits.

Limits are intentionally loose for MVP; tighten per business model.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PlanLimits:
    monthly_messages: int  # -1 = unlimited
    monthly_leads: int  # -1 = unlimited
    max_knowledge_chars: int  # system_prompt + products_data total
    bot_response_timeout: float  # seconds to wait for Groq


PLAN_CONFIG: Dict[str, PlanLimits] = {
    "FREE": PlanLimits(
        monthly_messages=500,
        monthly_leads=50,
        max_knowledge_chars=4_000,
        bot_response_timeout=15.0,
    ),
    "PRO": PlanLimits(
        monthly_messages=10_000,
        monthly_leads=1_000,
        max_knowledge_chars=8_000,
        bot_response_timeout=15.0,
    ),
    "ENTERPRISE": PlanLimits(
        monthly_messages=-1,
        monthly_leads=-1,
        max_knowledge_chars=15_000,
        bot_response_timeout=20.0,
    ),
}


def get_limits(plan: str) -> PlanLimits:
    return PLAN_CONFIG.get(plan.upper(), PLAN_CONFIG["FREE"])


def check_message_quota(plan: str, monthly_messages_used: int) -> bool:
    """Returns True if the company is within quota (allowed to send)."""
    limits = get_limits(plan)
    if limits.monthly_messages == -1:
        return True
    return monthly_messages_used < limits.monthly_messages


def check_lead_quota(plan: str, monthly_leads_used: int) -> bool:
    limits = get_limits(plan)
    if limits.monthly_leads == -1:
        return True
    return monthly_leads_used < limits.monthly_leads
