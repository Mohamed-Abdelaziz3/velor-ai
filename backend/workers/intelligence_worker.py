import os
import json
import logging
from database import SessionLocal, Lead, LeadMemory, LeadIntelligenceSnapshot, ActivityLog, SystemEvent
from groq import AsyncGroq

log = logging.getLogger("adam.intelligence")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LEGACY_INTELLIGENCE_WORKER_ENABLED = os.getenv("ENABLE_LEGACY_INTELLIGENCE_WORKER", "false").strip().lower() in {"1", "true", "yes"}
try:
    groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except Exception:
    groq_client = None


async def rebuild_lead_intelligence_task(company_id: str, lead_id: int):
    if not LEGACY_INTELLIGENCE_WORKER_ENABLED:
        log.info("Legacy intelligence worker is disabled; skipping advisory rebuild for lead %s.", lead_id)
        return
    if not groq_client:
        log.error("GROQ_API_KEY missing, skipping intelligence rebuild.")
        return

    log.info(f"Rebuilding intelligence for lead {lead_id}")

    with SessionLocal() as session:
        lead = (
            session.query(Lead)
            .filter(Lead.id == lead_id, Lead.company_id == company_id, Lead.is_deleted == False)
            .first()
        )
        if not lead:
            return

        memory = (
            session.query(LeadMemory)
            .join(Lead, LeadMemory.lead_id == Lead.id)
            .filter(
                LeadMemory.lead_id == lead_id,
                Lead.company_id == company_id,
                Lead.is_deleted == False,
            )
            .first()
        )
        activities = (
            session.query(ActivityLog)
            .join(Lead, ActivityLog.lead_id == Lead.id)
            .filter(
                ActivityLog.lead_id == lead_id,
                Lead.company_id == company_id,
                Lead.is_deleted == False,
            )
            .order_by(ActivityLog.timestamp.desc())
            .limit(10)
            .all()
        )

        memory_text = ""
        if memory:
            memory_text = f"""
Customer Summary: {memory.customer_summary}
Product Interest: {memory.product_interest}
Budget: {memory.budget}
Preferences: {memory.preferences}
"""

        recent_events = ""
        for act in activities:
            recent_events += f"[{act.timestamp}] {act.action_type}: {act.description}\n"

    system_prompt = f"""You are Velor, an elite AI Chief of Staff and Sales Strategist. Your task is to analyze the current state of a deal and generate an executive intelligence brief and execution plan.

[DEAL CONTEXT]
Stage: {lead.stage}
Status: {lead.status}
Deal Temperature: {lead.temperature}
Conversation State: {lead.conversation_state}

[CUSTOMER MEMORY]
{memory_text if memory_text.strip() else "No structured memory yet."}

[RECENT EVENTS]
{recent_events if recent_events.strip() else "No recent events."}

You must output a strictly valid JSON object representing the LeadIntelligenceSnapshot. Do not include markdown formatting.
IMPORTANT: You MUST write the values for why_here, why_summary, action_reason, next_best_action, why_matter, and expected_outcome entirely in the Arabic language.

Required JSON structure:
{{
  "priority_score": 0-100 (Integer, how urgent/high-intent this deal is),
  "lost_risk_score": 0-100 (Integer, how likely we are to lose this deal),
  "why_here": "Brief explanation of the primary signal or intent that makes this deal noteworthy right now.",
  "why_summary": "What just changed? (e.g. 'Customer asked for a discount on annual billing.')",
  "action_reason": "Exact quote from the customer or explicit evidence for the change.",
  "next_best_action": "The recommended next step for the human rep.",
  "why_matter": "Why taking this action matters to the business.",
  "expected_outcome": "The predicted outcome of taking this action.",
  "execution_sequence": [
    {{ "id": 1, "label": "Send Discount", "sublabel": "10% Off", "icon_name": "FiSend", "status": "current" }},
    {{ "id": 2, "label": "Schedule Call", "sublabel": "Next Step", "icon_name": "FiPhoneCall", "status": "pending" }}
  ]
}}

Rules for execution_sequence:
- Generate exactly 3 to 4 sequential steps tailored to the exact deal stage.
- One step MUST have status="current" (representing the next_best_action).
- Previous steps should be "completed", future steps should be "pending".
- Valid icon_names (mapped to React Icons): "FiSend", "FiPhoneCall", "FiFileText", "FiCheckCircle", "FiEdit3".
"""

    try:
        response = await groq_client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            max_tokens=int(os.getenv("GROQ_MAX_TOKENS", 1000)),
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content.strip()
        data = json.loads(raw_content)

        with SessionLocal() as session:
            snapshot = (
                session.query(LeadIntelligenceSnapshot)
                .join(Lead, LeadIntelligenceSnapshot.lead_id == Lead.id)
                .filter(
                    LeadIntelligenceSnapshot.lead_id == lead_id,
                    Lead.company_id == company_id,
                    Lead.is_deleted == False,
                )
                .first()
            )
            if not snapshot:
                snapshot = LeadIntelligenceSnapshot(lead_id=lead_id)
                session.add(snapshot)

            snapshot.priority_score = int(data.get("priority_score", 0))
            snapshot.lost_risk_score = int(data.get("lost_risk_score", 0))
            snapshot.why_here = data.get("why_here", "")
            snapshot.why_summary = data.get("why_summary", "")
            snapshot.action_reason = data.get("action_reason", "")
            snapshot.next_best_action = data.get("next_best_action", "")
            snapshot.why_matter = data.get("why_matter", "")
            snapshot.expected_outcome = data.get("expected_outcome", "")

            seq = data.get("execution_sequence", [])
            snapshot.execution_sequence = json.dumps(seq)

            # Fire intelligence.updated event for SSE push
            evt = SystemEvent(
                company_id=company_id,
                event_type="legacy_intelligence.updated",
                payload=json.dumps(
                    {
                        "lead_id": lead_id,
                        "live_brief": {
                            "priority_score": snapshot.priority_score,
                            "lost_risk_score": snapshot.lost_risk_score,
                            "why_here": snapshot.why_here,
                            "observation": snapshot.why_summary,
                            "evidence": snapshot.action_reason,
                            "recommendation": snapshot.next_best_action,
                            "why_matter": snapshot.why_matter,
                            "expected_outcome": snapshot.expected_outcome,
                            "execution_sequence": seq,
                        },
                    }
                ),
            )
            session.add(evt)

            session.commit()
            log.info(f"Intelligence rebuilt successfully for lead {lead_id}")

    except Exception as e:
        log.error(f"Failed to rebuild lead intelligence: {e}")
