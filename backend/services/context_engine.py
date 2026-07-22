import os
import json
from sqlalchemy.orm import Session
from database import SessionLocal, Lead, Message
from brain import groq_client
import logging

logger = logging.getLogger(__name__)


def _score_conversation_locally(conversation_text: str) -> tuple[str, float]:
    text = conversation_text.lower()
    score = 50.0
    if any(word in text for word in ["price", "pricing", "cost", "سعر", "الاسعار", "السعر", "تكلفة"]):
        score += 20
    if any(word in text for word in ["buy", "subscribe", "demo", "call", "اشتري", "شراء", "ديمو", "اتصال", "عايز"]):
        score += 25
    if any(word in text for word in ["expensive", "cancel", "غالي", "الغاء", "مش مناسب", "زعلان"]):
        score -= 25
    if any(word in text for word in ["01"]) or any(ch.isdigit() for ch in text):
        score += 10
    score = max(0.0, min(100.0, score))
    summary = "ملخص تلقائي: تم حفظ المحادثة وتحليلها محليًا. "
    if score >= 75:
        summary += "العميل يظهر نية شراء قوية ويستحق متابعة سريعة."
    elif score >= 45:
        summary += "العميل مهتم ويحتاج تأهيل أو توضيح إضافي."
    else:
        summary += "العميل منخفض النية أو يحتاج معالجة اعتراضات."
    return summary, score


async def summarize_conversation(company_id: str, user_id: str):
    """
    Summarizes the last 15 messages of a conversation and generates an intent score.
    Updates the Lead model with 'summary' and 'intent_score'.
    """
    db: Session = SessionLocal()
    try:
        from database import get_phone_variants

        variants = get_phone_variants(user_id)

        lead = (
            db.query(Lead)
            .filter(
                Lead.company_id == company_id,
                (Lead.whatsapp_number.in_(variants))
                | (Lead.phone.in_(variants))
                | (Lead.external_customer_id == str(user_id)),
            )
            .first()
        )

        if not lead:
            logger.warning(f"summarize_conversation: Lead not found for {user_id}.")
            return

        # Fetch last 15 messages for this lead's whatsapp_number or phone
        messages = (
            db.query(Message)
            .filter(
                Message.company_id == lead.company_id,
                (Message.user_id.in_(variants)) | (Message.user_id == str(user_id)),
            )
            .order_by(Message.id.desc())
            .limit(15)
            .all()
        )

        if not messages:
            return

        messages.reverse()  # chronological order

        conversation_text = ""
        for msg in messages:
            role = "Customer" if msg.direction == "incoming" else "Agent"
            conversation_text += f"{role}: {msg.message}\n"

        system_prompt = """You are an expert sales analyst and conversation summarizer.
Your task is to analyze the following conversation between a Customer and a Sales Agent and generate an intelligence briefing.

Follow these strict rules to calculate the 'intent_score' (starting from a base of 50):
- Add +30 for explicit buying questions (e.g., asking for pricing, timeline, or next steps).
- Add +20 for providing personal contact data (e.g., email, phone number).
- Subtract -40 for ignoring messages after pricing is revealed or expressing disinterest.
- Subtract -50 for explicit anger, frustration, or clear deal-breakers.
Ensure the final intent_score is between 0 and 100.

Step 1: Use Chain-of-Thought reasoning to evaluate the conversation based on the criteria above.
Step 2: Write a 2-sentence executive summary in Arabic summarizing the customer's current position.
Step 3: Output the final result STRICTLY as a JSON object containing 'intent_score' (number) and 'summary' (string).

Example JSON Output:
{
  "reasoning": "The customer asked about pricing (+30) and provided their email (+20). Total = 50 + 30 + 20 = 100. They are very interested.",
  "summary": "العميل مهتم جداً بالباقة الاحترافية وطلب تفاصيل الأسعار. تم إرسال الفاتورة وهو جاهز لإتمام عملية الدفع.",
  "intent_score": 100
}
"""

        try:
            response = await groq_client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": conversation_text}],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content.strip()
            result_json = json.loads(result_text)

            summary = result_json.get("summary", "")
            intent_score = float(result_json.get("intent_score", 0.0))

            lead.summary = summary
            lead.intent_score = intent_score
            db.commit()

            logger.info(f"Successfully summarized conversation for {user_id}. Score: {intent_score}")

        except Exception as e:
            logger.error(f"Error calling Groq for summarization: {e}")
            db.rollback()
            summary, intent_score = _score_conversation_locally(conversation_text)
            lead.summary = summary
            lead.intent_score = intent_score
            db.commit()

    except Exception as e:
        logger.error(f"Error in summarize_conversation: {e}")
    finally:
        db.close()
