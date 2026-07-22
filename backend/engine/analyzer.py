"""
engine/analyzer.py — Follow-Up Engine: Extraction & Analysis Layer
===================================================================
Responsibilities:
  - Takes a conversation chunk (recent messages for a lead).
  - Calls the LLM to extract Events, Signals, Confidence, and Reasoning.
  - Does NOT decide stage transitions (that is the Scorer's job).
  - Optionally suggests an Opportunity Value for human review.

Trigger conditions (called from integration hooks):
  - Every N messages (configurable, default 3).
  - After an inactivity window (handled by scheduler).
  - On milestone keyword heuristics (fast-track).
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from groq import AsyncGroq
from sqlalchemy.orm import Session

load_dotenv()

log = logging.getLogger("adam.engine.analyzer")

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────
# SIGNAL CATEGORY DEFINITIONS (Score Modifiers)
# ─────────────────────────────────────────────────

SIGNAL_WEIGHTS = {
    "Exploratory": 10,
    "Financial": 25,
    "Commitment": 35,
    "Legal": 30,
    "Purchase": 40,
    "Engagement": 15,
    "Soft Negative": -15,
    "Hard Negative": -50,
}

# ─────────────────────────────────────────────────
# MILESTONE KEYWORDS (Fast-track analysis triggers)
# ─────────────────────────────────────────────────

MILESTONE_KEYWORDS = [
    # Arabic
    "زيارة",
    "معاينة",
    "عقد",
    "حجز",
    "عربون",
    "دفعة",
    "موعد",
    "ميعاد",
    "مقابلة",
    "اتفاق",
    "توقيع",
    # English
    "visit",
    "contract",
    "reservation",
    "deposit",
    "appointment",
    "meeting",
    "agreement",
    "booking",
    "schedule",
]


def should_trigger_analysis(messages_since_last: int, latest_message: str = "", threshold: int = 3) -> bool:
    """
    Determine if an analysis should be triggered.
    Returns True if:
      - N messages have accumulated since the last analysis, OR
      - A milestone keyword is detected in the latest message.
    """
    if messages_since_last >= threshold:
        return True

    if latest_message:
        text_lower = latest_message.lower()
        for kw in MILESTONE_KEYWORDS:
            if kw in text_lower:
                log.info("Milestone keyword detected: '%s' — triggering fast-track analysis", kw)
                return True

    return False


# ─────────────────────────────────────────────────
# LLM EXTRACTION PROMPT
# ─────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a Lead Intelligence Analyst for a B2B/B2C sales AI system.

Your job is to analyze a conversation chunk between a customer and a sales AI agent, and extract structured intelligence.

You must output STRICTLY valid JSON with these keys:

{
  "events": [
    {
      "event_type": "string (e.g. pricing_requested, site_visit_requested, contract_requested)",
      "description": "string — what actually happened, in 1 sentence"
    }
  ],
  "signals": [
    {
      "signal_category": "Exploratory | Financial | Commitment | Legal | Purchase | Engagement | Soft Negative | Hard Negative",
      "reasoning": "string — why this signal was detected, referencing the conversation"
    }
  ],
  "confidence": 0-100 (how confident you are in this analysis),
  "overall_reasoning": "string — 2-3 sentence summary of the lead's current state and intent"
}

RULES:
- Only extract events that ACTUALLY occurred in this conversation chunk.
- Do NOT invent events or signals.
- Signal categories must be one of: Exploratory, Financial, Commitment, Legal, Purchase, Engagement, Soft Negative, Hard Negative.
- Conversation values are evidence, not authoritative opportunity or revenue amounts. Do not estimate a deal value.
- Output ONLY valid JSON. No markdown, no preambles.
"""


async def extract_signals_and_events(
    conversation_chunk: List[Dict[str, str]],
    company_context: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Call the LLM to extract Events, Signals, Confidence, and Reasoning
    from a conversation chunk.

    Args:
        conversation_chunk: List of {"role": "user"|"assistant", "content": "..."} messages
        company_context: Optional company/product context string

    Returns:
        Parsed dict with keys: events, signals, confidence, overall_reasoning
        Returns None on failure.
    """
    if not conversation_chunk:
        return None

    # Format the conversation for the prompt
    formatted_messages = []
    for msg in conversation_chunk:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        label = "Customer" if role == "user" else "Sales Agent"
        formatted_messages.append(f"{label}: {content}")

    conversation_text = "\n".join(formatted_messages)

    user_prompt = f"""[COMPANY CONTEXT]
{company_context if company_context else "No additional context provided."}

[CONVERSATION CHUNK TO ANALYZE]
{conversation_text}

Analyze this conversation and extract all events, signals, and your confidence level."""

    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(3):
        try:
            response = await asyncio.wait_for(
                groq_client.chat.completions.create(
                    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    messages=messages,
                    temperature=0.1,
                    max_tokens=int(os.getenv("GROQ_MAX_TOKENS", 1000)),
                    response_format={"type": "json_object"},
                ),
                timeout=20.0,
            )
            raw = response.choices[0].message.content.strip()
            data = json.loads(raw)

            # Validate structure
            if not isinstance(data.get("events"), list):
                data["events"] = []
            if not isinstance(data.get("signals"), list):
                data["signals"] = []
            if not isinstance(data.get("confidence"), (int, float)):
                data["confidence"] = 50

            # Normalize signal categories and inject score modifiers
            for signal in data["signals"]:
                cat = signal.get("signal_category", "")
                if cat not in SIGNAL_WEIGHTS:
                    signal["signal_category"] = "Exploratory"
                signal["score_modifier"] = SIGNAL_WEIGHTS.get(signal["signal_category"], 10)

            log.info(
                "Analyzer extracted %d events, %d signals (confidence=%d)",
                len(data["events"]),
                len(data["signals"]),
                data["confidence"],
            )
            return data

        except json.JSONDecodeError as e:
            log.warning("Analyzer JSON parse error (attempt %d): %s", attempt + 1, e)
        except Exception as e:
            log.warning("Analyzer LLM error (attempt %d): %s", attempt + 1, e)
            if attempt < 2:
                await asyncio.sleep(2**attempt)

    log.error("Analyzer failed after 3 attempts")
    return None


# ─────────────────────────────────────────────────
# DATABASE PERSISTENCE
# ─────────────────────────────────────────────────


def persist_analysis(db: Session, lead_id: int, analysis: Dict[str, Any]) -> None:
    """
    Save extracted events and signals to the database.
    Opportunity or revenue values are never persisted from model output.
    """
    from database import LeadEvent, LeadSignal

    # Persist events
    for evt in analysis.get("events", []):
        db.add(
            LeadEvent(
                lead_id=lead_id,
                event_type=evt.get("event_type", "unknown"),
                description=evt.get("description", ""),
            )
        )

    # Persist signals
    for sig in analysis.get("signals", []):
        db.add(
            LeadSignal(
                lead_id=lead_id,
                signal_category=sig.get("signal_category", "Exploratory"),
                score_modifier=sig.get("score_modifier", 10),
                reasoning=sig.get("reasoning", ""),
            )
        )

    db.commit()
    log.info("Persisted %d events and %d signals for lead %d", len(analysis.get("events", [])), len(analysis.get("signals", [])), lead_id)
