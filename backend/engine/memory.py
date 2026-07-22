import os
import json
import logging
from datetime import datetime, timezone
from database import SessionLocal, Lead, LeadMemory, get_user_history
from groq import AsyncGroq
import asyncio

log = logging.getLogger("adam.memory")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
try:
    groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except Exception:
    groq_client = None


async def rebuild_lead_memory_task(company_id: str, user_id: str, lead_id: int):
    if not groq_client:
        log.error("GROQ_API_KEY missing, skipping memory rebuild.")
        return

    log.info(f"Rebuilding memory for lead {lead_id}")

    with SessionLocal() as session:
        lead = session.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return

        memory = session.query(LeadMemory).filter(LeadMemory.lead_id == lead_id).first()
        if not memory:
            memory = LeadMemory(lead_id=lead_id)
            session.add(memory)
            session.commit()

        # Get history
        history = get_user_history(session, company_id, user_id, limit=20)
        if not history:
            return

        history_text = ""
        for msg in history:
            role_val = msg.get("role") or msg.get("sender")
            content_val = msg.get("content") or msg.get("message")
            role = "AI" if role_val == "assistant" else "Customer"
            history_text += f"{role}: {content_val}\n"

        current_memory_text = ""
        if memory.customer_summary:
            current_memory_text += f"Customer Summary: {memory.customer_summary}\n"
        if memory.product_interest:
            current_memory_text += f"Product Interest: {memory.product_interest}\n"
        if memory.budget:
            current_memory_text += f"Budget: {memory.budget}\n"
        if memory.preferences:
            current_memory_text += f"Preferences: {memory.preferences}\n"
        if memory.purchase_history:
            current_memory_text += f"Purchase History: {memory.purchase_history}\n"

    system_prompt = f"""You are an elite Sales Analyst AI. Your task is to update the Known Customer Facts based on the recent conversation history.

[CURRENT MEMORY]
{current_memory_text if current_memory_text else "No current memory."}

[CONVERSATION HISTORY]
{history_text}

You must extract and update the following business facts. For each fact, output a JSON object containing a "value" (string) and a "confidence" (number between 0.0 and 1.0). If a fact is unknown or not mentioned, set value to null.
Only update facts if new, meaningful information is provided. Compress the facts into concise business language (e.g. "Interested in XYZ", "7000 EGP"). Do not store full chat logs.

Strictly output valid JSON with the following keys:
- "customer_summary": {{"value": "...", "confidence": 0.9}}
- "product_interest": {{"value": "...", "confidence": 0.9}}
- "budget": {{"value": "...", "confidence": 0.9}}
- "preferences": {{"value": "...", "confidence": 0.9}}
- "purchase_history": {{"value": "...", "confidence": 0.9}}
"""

    try:
        response = await groq_client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            max_tokens=int(os.getenv("GROQ_MAX_TOKENS", 500)),
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content.strip()
        data = json.loads(raw_content)

        with SessionLocal() as session:
            memory = session.query(LeadMemory).filter(LeadMemory.lead_id == lead_id).first()
            if memory:
                if data.get("customer_summary") and data["customer_summary"].get("value"):
                    memory.customer_summary = json.dumps(data["customer_summary"], ensure_ascii=False)
                if data.get("product_interest") and data["product_interest"].get("value"):
                    memory.product_interest = json.dumps(data["product_interest"], ensure_ascii=False)
                if data.get("budget") and data["budget"].get("value"):
                    memory.budget = json.dumps(data["budget"], ensure_ascii=False)
                if data.get("preferences") and data["preferences"].get("value"):
                    memory.preferences = json.dumps(data["preferences"], ensure_ascii=False)
                if data.get("purchase_history") and data["purchase_history"].get("value"):
                    memory.purchase_history = json.dumps(data["purchase_history"], ensure_ascii=False)

                memory.last_memory_rebuild_at = datetime.now(timezone.utc)
                session.commit()
                log.info(f"Memory rebuilt successfully for lead {lead_id}")

    except Exception as e:
        log.error(f"Failed to rebuild lead memory: {e}")
