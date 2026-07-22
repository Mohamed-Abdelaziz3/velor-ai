"""
engine/scorer.py — Follow-Up Engine: Deterministic Scoring & Decision Layer
=============================================================================
Responsibilities:
  - Computes Intent Score (sum of signal modifiers, clamped 0-100).
  - Computes Priority Score (weighted: intent, recency, opportunity, lost risk).
  - Computes Lost Risk Score (stage-aware silence detection).
  - Enforces Stage Transitions deterministically (NOT by LLM).
  - Generates Next Best Action and Why Summary.
  - Persists everything to LeadIntelligenceSnapshot.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

log = logging.getLogger("adam.engine.scorer")

# ─────────────────────────────────────────────────
# STAGE DEFINITIONS (ordered by progression)
# ─────────────────────────────────────────────────

STAGES = [
    "Information Gathering",
    "Interested",
    "High Intent",
    "Site Visit Scheduled",
    "Site Visit Completed",
    "Purchase Ready",
    "Won",
    "Lost Candidate",
    "Lost",
]

STAGE_ORDER = {stage: i for i, stage in enumerate(STAGES)}

# ─────────────────────────────────────────────────
# STAGE TRANSITION RULES (deterministic)
# ─────────────────────────────────────────────────

# Minimum intent score + required signal categories for each transition
TRANSITION_RULES = {
    "Interested": {
        "min_intent": 15,
        "min_confidence": 60,
        "required_categories": [],  # Any signal is enough
    },
    "High Intent": {
        "min_intent": 40,
        "min_confidence": 70,
        "required_categories": ["Financial"],  # Must have at least 1 Financial signal
    },
    "Site Visit Scheduled": {
        "min_intent": 50,
        "min_confidence": 80,
        "required_categories": ["Commitment"],
        "milestone_events": ["site_visit_scheduled", "meeting_scheduled", "appointment_confirmed"],
    },
    "Purchase Ready": {
        "min_intent": 65,
        "min_confidence": 75,
        "required_categories": ["Purchase"],
        "human_gate": "Site Visit Completed",
        "milestone_events": ["contract_requested", "reservation_requested", "payment_requested", "booking_intent_expressed"],
    },
}

# Stages that require explicit human confirmation
HUMAN_GATED_STAGES = {"Site Visit Completed", "Won", "Lost"}

# ─────────────────────────────────────────────────
# LOST RISK CALCULATION (stage-aware)
# ─────────────────────────────────────────────────

# Hours of silence before risk starts climbing, per stage
SILENCE_THRESHOLDS = {
    "High Intent": 24,
    "Site Visit Scheduled": 48,
    "Site Visit Completed": 72,
    "Purchase Ready": 24,
    "Interested": 72,
    "Information Gathering": 120,
}


def _compute_lost_risk(stage: str, hours_since_last_activity: float, has_hard_negative: bool) -> int:
    """
    Compute lost risk score (0-100).
    Higher stages with longer silence = higher risk.
    Hard negative signals immediately push risk to 80+.
    """
    if has_hard_negative:
        return min(90, 80 + int(hours_since_last_activity / 24) * 5)

    threshold = SILENCE_THRESHOLDS.get(stage, 120)
    if hours_since_last_activity <= threshold:
        return 0

    # Risk grows proportionally to how far past the threshold we are
    overage_hours = hours_since_last_activity - threshold
    stage_weight = STAGE_ORDER.get(stage, 0)
    risk = min(100, int((overage_hours / threshold) * 50 + stage_weight * 8))
    return risk


# ─────────────────────────────────────────────────
# INTENT SCORE CALCULATION
# ─────────────────────────────────────────────────


def _compute_intent_score(signals) -> int:
    """Sum max signal modifier per category, clamped to 0-100."""
    category_maxes = {}
    for s in signals:
        if s.signal_category not in category_maxes:
            category_maxes[s.signal_category] = s.score_modifier
        else:
            category_maxes[s.signal_category] = max(category_maxes[s.signal_category], s.score_modifier)

    total = sum(category_maxes.values())
    return max(0, min(100, total))


# ─────────────────────────────────────────────────
# PRIORITY SCORE CALCULATION
# ─────────────────────────────────────────────────


def _compute_priority_score(
    intent_score: int,
    opportunity_value: Optional[float],
    hours_since_last_activity: float,
    lost_risk: int,
) -> int:
    """
    Weighted priority formula:
      - Intent Score:       40%
      - Opportunity Value:  30% (normalized, capped at 10M)
      - Recency:            20% (decays with silence)
      - Lost Risk:          10% (higher risk = higher priority to save)
    """
    # Normalize opportunity value (0-100 scale, 10M = 100)
    opp_normalized = 0
    if opportunity_value and opportunity_value > 0:
        opp_normalized = min(100, (opportunity_value / 10_000_000) * 100)

    # Recency score (100 = just now, decays over 7 days)
    recency = max(0, 100 - (hours_since_last_activity / 168) * 100)

    priority = intent_score * 0.4 + opp_normalized * 0.3 + recency * 0.2 + lost_risk * 0.1
    return max(0, min(100, int(priority)))


# ─────────────────────────────────────────────────
# STAGE TRANSITION ENGINE
# ─────────────────────────────────────────────────


def _determine_stage(
    current_stage: str,
    intent_score: int,
    confidence: int,
    signal_categories: set,
    event_types: set,
    has_hard_negative: bool,
) -> str:
    """
    Determine the correct stage based on accumulated signals and events.
    Only allows forward transitions (never auto-demotes).
    Human-gated stages are skipped unless manually set.
    """
    if has_hard_negative:
        # Don't auto-transition to Lost — mark as Lost Candidate for human review
        if current_stage not in ("Lost", "Lost Candidate", "Won"):
            return "Lost Candidate"

    current_order = STAGE_ORDER.get(current_stage, 0)

    # Try to advance through stages in order
    best_stage = current_stage

    for target_stage, rules in TRANSITION_RULES.items():
        target_order = STAGE_ORDER.get(target_stage, 0)

        # Skip if we're already at or past this stage
        if target_order <= current_order:
            continue

        # Check for milestone events that override standard thresholds
        has_milestone = False
        milestone_events = rules.get("milestone_events", [])
        if milestone_events and any(evt in event_types for evt in milestone_events):
            has_milestone = True

        if not has_milestone:
            # Skip human-gated stages
            if target_stage in HUMAN_GATED_STAGES:
                continue

            # Check if there's a human gate prerequisite
            human_gate = rules.get("human_gate")
            if human_gate and STAGE_ORDER.get(current_stage, 0) < STAGE_ORDER.get(human_gate, 0):
                continue

            # Check minimum intent
            if intent_score < rules.get("min_intent", 0):
                continue

            # Check minimum confidence
            if confidence < rules.get("min_confidence", 0):
                continue

            # Check required signal categories
            required_cats = rules.get("required_categories", [])
            if required_cats and not any(cat in signal_categories for cat in required_cats):
                continue

            # Check required events (if any)
            required_events = rules.get("required_events", [])
            if required_events and not any(evt in event_types for evt in required_events):
                continue

        # All checks passed — this transition is valid
        if STAGE_ORDER.get(target_stage, 0) > STAGE_ORDER.get(best_stage, 0):
            best_stage = target_stage

    return best_stage


# ─────────────────────────────────────────────────
# NEXT BEST ACTION GENERATOR
# ─────────────────────────────────────────────────


def _generate_next_action(stage: str, lost_risk: int, intent_score: int) -> tuple[str, str]:
    """Generate a human-readable recommended next action and reason."""
    if lost_risk >= 70:
        return "يُنصح بالمتابعة الفورية للعميل.", "يوجد خطر مرتفع لفقدان هذه الفرصة."

    actions = {
        "Information Gathering": ("بناء علاقة مع العميل والإجابة على استفساراته.", "العميل في مرحلة جمع المعلومات."),
        "Interested": ("مشاركة تفاصيل المشروع والأسعار المتاحة.", "العميل أبدى اهتماماً بالمنتج."),
        "High Intent": ("التواصل الهاتفي أو تحديد موعد لزيارة الموقع.", "العميل يظهر نية شراء قوية."),
        "Site Visit Scheduled": ("تأكيد موعد الزيارة وتجهيز العروض المناسبة.", "تم تحديد موعد للزيارة."),
        "Site Visit Completed": ("المتابعة بعد الزيارة لمعرفة الانطباع والخطوات القادمة.", "العميل أتم زيارة الموقع."),
        "Purchase Ready": ("إرسال تفاصيل الدفع أو إجراءات التعاقد.", "العميل جاهز لإتمام الشراء."),
        "Won": ("التأكد من رضا العميل وإتمام الإجراءات بنجاح.", "تم إغلاق الصفقة بنجاح."),
        "Lost Candidate": ("مراجعة أسباب الرفض ومحاولة إعادة التواصل مستقبلاً.", "العميل قرر عدم الشراء حالياً."),
        "Lost": ("أرشفة العميل لحملات إعادة الاستهداف.", "تم فقدان العميل."),
    }
    return actions.get(stage, ("مراجعة حالة العميل.", "تحتاج الحالة لمراجعة يدوية."))


def _generate_why_summary(
    stage: str, intent_score: int, confidence: int, signal_categories: set, event_types: set, hours_since_activity: float, lost_risk: int
) -> str:
    """Generate a structured explanation of why this lead matters."""
    import json

    why_matters = ""
    if stage == "Purchase Ready":
        why_matters = "العميل طلب تفاصيل الدفع ويبدو قريبًا من اتخاذ قرار الشراء."
    elif stage == "High Intent":
        why_matters = "العميل مهتم بالتفاصيل المالية والمواصفات ويظهر جدية عالية."
    elif lost_risk >= 70:
        why_matters = f"لم يرد العميل منذ {int(hours_since_activity/24)} أيام رغم وجود إشارات شراء واضحة."
    else:
        why_matters = "العميل يتفاعل بشكل إيجابي ويظهر اهتماماً ملحوظاً."

    # Map signals to Arabic business terms
    signal_map = {
        "pricing_requested": "السعر",
        "booking_requested": "معلومات الحجز",
        "site_visit_requested": "زيارة الموقع",
        "payment_requested": "تفاصيل الدفع",
        "booking_intent_expressed": "نية التعاقد",
        "purchase_declined": "رفض الشراء",
        "Financial": "المعلومات المالية",
        "Commitment": "الجدية",
        "Purchase": "الشراء",
        "Engagement": "التفاعل",
        "Exploratory": "الاستكشاف",
        "Hard Negative": "الرفض التام",
    }

    signals_detected = []
    for s in list(signal_categories) + list(event_types):
        if s in signal_map:
            signals_detected.append(signal_map[s])

    if signals_detected:
        key_signals = f"أبدى اهتمامًا بـ: {'، '.join(signals_detected)}."
    else:
        key_signals = "تفاعل عام دون تفاصيل محددة."

    risk_explanation = ""
    if lost_risk >= 70:
        risk_explanation = "يوجد خطر مرتفع لفقدان هذه الفرصة بسبب غياب التفاعل خلال الأيام الأخيرة."
    elif lost_risk >= 40:
        risk_explanation = "تراجع في مستوى التفاعل، ينصح بالمتابعة للحفاظ على حرارة العميل."
    else:
        risk_explanation = "تفاعل العميل صحي ومستمر."

    return json.dumps(
        {
            "why_this_lead_matters": why_matters,
            "key_buying_signals": [key_signals],
            "current_stage": stage,
            "lost_risk_explanation": risk_explanation,
        },
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────
# MAIN SCORING PIPELINE
# ─────────────────────────────────────────────────


def score_and_update_lead(db: Session, lead_id: int, analysis_confidence: int = 50, overall_reasoning: str = "") -> None:
    """
    Main entry point: Recompute all scores for a lead and update the
    LeadIntelligenceSnapshot.

    This is the ONLY function that modifies stages — the Analyzer never does.
    """
    from database import Lead, LeadSignal, LeadEvent, LeadIntelligenceSnapshot

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        log.warning("score_and_update_lead: Lead %d not found", lead_id)
        return

    # Gather all signals and events for this lead, ordered by time
    signals = db.query(LeadSignal).filter(LeadSignal.lead_id == lead_id).order_by(LeadSignal.timestamp.asc()).all()
    events = db.query(LeadEvent).filter(LeadEvent.lead_id == lead_id).all()

    signal_categories = {s.signal_category for s in signals}
    event_types = {e.event_type for e in events}

    # Dynamically calculate if there's an active hard negative
    has_hard_negative = False
    for s in signals:
        if s.signal_category == "Hard Negative":
            has_hard_negative = True
        elif s.signal_category in ("Purchase", "Commitment", "Financial"):
            # A newer strong positive signal resolves the older hard negative
            has_hard_negative = False

    # 1. Intent Score
    intent_score = _compute_intent_score(signals)

    # 2. Stage Transition
    new_stage = _determine_stage(
        current_stage=lead.stage,
        intent_score=intent_score,
        confidence=analysis_confidence,
        signal_categories=signal_categories,
        event_types=event_types,
        has_hard_negative=has_hard_negative,
    )

    if new_stage != lead.stage:
        log.info("Lead %d stage transition: %s → %s", lead_id, lead.stage, new_stage)
        lead.stage = new_stage

    # 3. Lost Risk (stage-aware)
    hours_since_activity = 0.0
    if lead.last_contact_date:
        delta = (
            datetime.now(timezone.utc) - lead.last_contact_date.replace(tzinfo=timezone.utc)
            if lead.last_contact_date.tzinfo is None
            else datetime.now(timezone.utc) - lead.last_contact_date
        )
        hours_since_activity = max(0, delta.total_seconds() / 3600)

    lost_risk = _compute_lost_risk(lead.stage, hours_since_activity, has_hard_negative)

    # 4. Priority Score
    priority_score = _compute_priority_score(
        intent_score=intent_score,
        opportunity_value=lead.opportunity_value,
        hours_since_last_activity=hours_since_activity,
        lost_risk=lost_risk,
    )

    # 5. Next Best Action & Why
    next_action, action_reason = _generate_next_action(lead.stage, lost_risk, intent_score)
    why_summary_json = _generate_why_summary(
        stage=lead.stage,
        intent_score=intent_score,
        confidence=analysis_confidence,
        signal_categories=signal_categories,
        event_types=event_types,
        hours_since_activity=hours_since_activity,
        lost_risk=lost_risk,
    )

    # 6. Persist to LeadIntelligenceSnapshot (upsert)
    snapshot = db.query(LeadIntelligenceSnapshot).filter(LeadIntelligenceSnapshot.lead_id == lead_id).first()

    if not snapshot:
        snapshot = LeadIntelligenceSnapshot(lead_id=lead_id)
        db.add(snapshot)

    is_terminal = lead.stage in ["Won", "Lost"]
    if not is_terminal:
        snapshot.intent_score = intent_score
        snapshot.priority_score = priority_score
        snapshot.confidence_score = analysis_confidence
        snapshot.lost_risk_score = lost_risk

    snapshot.next_best_action = next_action
    snapshot.action_reason = action_reason
    snapshot.why_summary = why_summary_json

    db.commit()

    log.info(
        "Lead %d scored: intent=%d priority=%d risk=%d stage=%s",
        lead_id,
        intent_score,
        priority_score,
        lost_risk,
        lead.stage,
    )
