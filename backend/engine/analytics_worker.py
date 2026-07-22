import os
import json
import logging
from datetime import datetime, timezone
from database import SessionLocal, Lead, LeadMemory, LeadAnalytics, get_user_history
from groq import AsyncGroq

log = logging.getLogger("adam.analytics_worker")


def _parse_json(text):
    """Parse provider JSON without importing the legacy V1 brain module."""
    try:
        value = json.loads(text or "")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
try:
    groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except Exception:
    groq_client = None

ANALYTICS_PROMPT = """You are a Lead CRM Data Analyst for VELOR.
Task: Analyze the provided conversation history and LeadMemory to identify product interest patterns.

Instructions:
1. Scan the conversation for any explicit or implicit interest in products/services listed in the company knowledge base.
2. Maintain a frequency count of requested products.
3. If a product is mentioned, identify the sentiment:
   - Positive/High Intent (wants to buy/ask details)
   - Exploratory (just asking/comparing)
   - Negative (complaint/price objection)
4. Output the result in the following JSON format:

{
  "top_requested_products": [
    {"product_name": "string", "request_count": int, "sentiment_summary": "string"}
  ],
  "trending_topics": ["list of common questions about products"],
  "business_opportunity": "One-line suggestion on how to improve sales for these top products."
}

Context:
- Use the 'customer_summary' and 'product_interest' fields from the LeadMemory.
- If the intent is unclear, label the sentiment as "Exploratory".
- Only include products mentioned in the conversation history provided.
"""


async def analyze_lead_product_interest(company_id: str, user_id: str, lead_id: int):
    if not groq_client:
        log.error("GROQ_API_KEY missing, skipping product analytics.")
        return None

    log.info(f"Running product analytics for lead {lead_id}")

    with SessionLocal() as session:
        lead = session.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
        if not lead:
            log.warning(f"Lead {lead_id} not found.")
            return None

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

        # Get history
        history = get_user_history(session, company_id, user_id, limit=50)
        if not history:
            log.warning(f"No history found for lead {lead_id}.")
            return None

        history_text = ""
        for msg in history:
            role = "AI" if msg["role"] == "assistant" else "Customer"
            history_text += f"{role}: {msg['content']}\n"

        memory_context = ""
        if memory:
            if memory.customer_summary:
                memory_context += f"Customer Summary: {memory.customer_summary}\n"
            if memory.product_interest:
                memory_context += f"Product Interest: {memory.product_interest}\n"

    user_prompt = f"""[CURRENT LEAD MEMORY]
{memory_context if memory_context else "No prior memory available."}

[CONVERSATION HISTORY]
{history_text}

Perform the product interest analysis based on the instructions."""

    try:
        response = await groq_client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[{"role": "system", "content": ANALYTICS_PROMPT}, {"role": "user", "content": user_prompt}],
            temperature=0.1,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content.strip()
        data = _parse_json(raw_content)

        with SessionLocal() as session:
            analytics = (
                session.query(LeadAnalytics)
                .join(Lead, LeadAnalytics.lead_id == Lead.id)
                .filter(
                    LeadAnalytics.lead_id == lead_id,
                    Lead.company_id == company_id,
                    Lead.is_deleted == False,
                )
                .first()
            )
            if not analytics:
                analytics = LeadAnalytics(lead_id=lead_id)
                session.add(analytics)

            analytics.top_requested_products = json.dumps(data.get("top_requested_products", []), ensure_ascii=False)
            analytics.trending_topics = json.dumps(data.get("trending_topics", []), ensure_ascii=False)
            analytics.business_opportunity = data.get("business_opportunity", "")
            analytics.last_analyzed_at = datetime.now(timezone.utc)

            session.commit()
            log.info(f"Product analytics saved successfully for lead {lead_id}")
            return data

    except Exception as e:
        log.error(f"Failed to run product analytics: {e}")
        return None
