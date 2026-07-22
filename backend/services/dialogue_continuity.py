import re
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("adam.dialogue_continuity")

# DialogueAct types
class DialogueAct:
    GREETING = "GREETING"
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    YES = "YES"
    NO = "NO"
    CHOICE = "CHOICE"
    SHORT_ANSWER = "SHORT_ANSWER"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    CONTINUE = "CONTINUE"
    PRODUCT_REFERENCE = "PRODUCT_REFERENCE"
    PRODUCT_SELECTION = "PRODUCT_SELECTION"
    QUESTION = "QUESTION"
    PRICE_OBJECTION = "PRICE_OBJECTION"
    BUDGET = "BUDGET"
    COMPARISON = "COMPARISON"
    PURCHASE_ADVANCE = "PURCHASE_ADVANCE"
    CANCEL = "CANCEL"
    EXPLICIT_UNKNOWN_FACT_REQUEST = "EXPLICIT_UNKNOWN_FACT_REQUEST"
    UNRESOLVED_DIALOGUE = "UNRESOLVED_DIALOGUE"

# ExpectedAnswerType types
class ExpectedAnswerType:
    YES_NO = "YES_NO"
    ONE_OF_OPTIONS = "ONE_OF_OPTIONS"
    BUDGET_AMOUNT = "BUDGET_AMOUNT"
    PRODUCT_NAME = "PRODUCT_NAME"
    USAGE_DURATION = "USAGE_DURATION"
    QUANTITY = "QUANTITY"
    CONTACT = "CONTACT"
    FREE_TEXT = "FREE_TEXT"
    CONFIRMATION = "CONFIRMATION"


def normalize_arabic_text(text: str) -> str:
    """Normalize Arabic text for robust keyword matching."""
    if not text:
        return ""
    t = text.strip().casefold()
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = t.replace("ة", "ه")
    t = t.replace("ى", "ي")
    t = re.sub(r"[\u064B-\u0652]", "", t)
    return t


def is_greeting(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    greetings = ["السلام", "عليكم", "مرحبا", "اهلا", "سلام", "hi", "hello", "يا بني ادم", "مساء الخير", "صباح الخير", "صباح", "مساء", "هاي", "هلا"]
    # Check if text is short and contains greeting words
    words = normalized.split()
    if len(words) <= 3 and any(g in normalized for g in greetings):
        return True
    return False


def is_acknowledgement(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    words = [w.strip() for w in normalized.split() if w.strip()]
    if not words:
        return False
    ack_words = ["تمام", "ماشي", "اوكي", "حلو", "جميل", "طيب", "طب", "ok", "okay", "تسلم", "شكرا", "شغاله", "شغال", "حاضر", "مفهوم", "علم"]
    # If the text is short and contains acknowledgement words
    if len(words) <= 2 and any(ack in words for ack in ack_words):
        return True
    return False


def is_yes(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    words = [w.strip() for w in normalized.split() if w.strip()]
    if not words:
        return False
    yes_words = ["اه", "نعم", "ايوه", "تمام", "ماشي", "اوكي", "اكيد", "طبعا", "طبعاً", "yes", "yeah", "yep", "ok", "okay", "يب", "بالظبط", "فعلا"]
    if len(words) <= 2 and any(yw in words for yw in yes_words):
        return True
    return False


def is_no(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    words = [w.strip() for w in normalized.split() if w.strip()]
    if not words:
        return False
    no_words = ["لا", "لأ", "مش عايز", "لا شكرا", "no", "nope", "مش حابب", "لأ مش ده", "مش ده", "مش هو", "بلاش", "ابدا", "مرفوض"]
    if len(words) <= 3 and any(nw in normalized for nw in no_words):
        return True
    return False


def is_continue(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    words = [w.strip() for w in normalized.split() if w.strip()]
    if not words:
        return False
    continue_words = ["كمل", "وبعدين", "طب وبعدين", "استمر", "continue", "قولي", "حلو كمل", "قولي تاني", "ايه كمان", "ايه", "توضيح", "تابع"]
    if len(words) <= 2 and any(cw in normalized for cw in continue_words):
        return True
    return False


def is_cancel(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    words = [w.strip() for w in normalized.split() if w.strip()]
    if not words:
        return False
    cancel_words = ["الغاء", "كنسل", "الغي", "cancel", "تراجع"]
    if len(words) <= 2 and any(cw in normalized for cw in cancel_words):
        return True
    return False


def is_price_objection(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    objection_words = ["غالي", "كتير", "expensive", "too much", "سعر عالي", "غاليه"]
    return any(word in normalized for word in objection_words)


def is_budget_constraint(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    budget_words = ["معايا", "ميزانيتي", "حدي", "اخري", "سقفي", "budget", "limit", "سقف", "ميزانية", "ميزانيه", "ادفع", "ادفعها", "دفع"]
    return any(word in normalized for word in budget_words) or bool(re.search(r"(\d{3,8})\s*(?:جنيه|جنية|egp)", normalized))


def is_factual_question(text: str) -> bool:
    normalized = normalize_arabic_text(text)
    # Factual question indicators
    factual_words = ["خصم", "ضمان", "شحن", "توصيل", "مكتب", "عنوان", "فرع", "سعر", "بكام", "مواصفات", "تفاصيل", "فرق"]
    question_words = ["كام", "بكام", "فين", "ليه", "ازاي", "هل", "ما هو", "ايه", "شو", "سعر", "price", "delivery", "shipping", "warranty"]
    return any(w in normalized for w in factual_words) or any(w in normalized for w in question_words)


def extract_explicit_number(text: str) -> Optional[float]:
    nums = re.findall(r"\d+", text)
    if nums:
        try:
            return float(nums[-1])
        except (ValueError, TypeError):
            pass
    return None


def resolve_dialogue_continuity(db: Any, lead: Any, customer_text: str) -> Dict[str, Any]:
    """
    Main dialogue resolution flow. Runs BEFORE commercial response plan is built.
    Analyzes active pending question, customer response, resolves references,
    detects topic changes, and decides on direct override replies or plan updates.
    """
    text = customer_text.strip()
    normalized = normalize_arabic_text(text)
    
    # Load pending question
    pending_q = None
    if lead.pending_question:
        try:
            pending_q = json.loads(lead.pending_question)
        except Exception:
            log.exception("Failed to parse pending question JSON")
            
    # Derive recent products from context
    recent_products = []
    if lead.memory and lead.memory.product_interest:
        try:
            # We can also parse from database
            pass
        except Exception:
            pass
            
    # Detect raw dialogue characteristics
    greeting_act = is_greeting(text)
    ack_act = is_acknowledgement(text)
    yes_act = is_yes(text)
    no_act = is_no(text)
    cont_act = is_continue(text)
    cancel_act = is_cancel(text)
    price_obj_act = is_price_objection(text)
    budget_act = is_budget_constraint(text)
    fact_q_act = is_factual_question(text)
    
    # Default outputs
    dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
    resolved_product = None
    resolved_budget = None
    resolved_value = None
    topic_changed = False
    clarification_needed = False
    clarification_response = None
    override_reply = None
    
    # 1. Topic Change Detection
    # If customer ignores the active question and directly asks a new factual question
    if pending_q and not pending_q.get("resolved") and (fact_q_act or price_obj_act or budget_act):
        # Exception: if expected answer is budget and customer gives budget, it is not a topic change
        is_answering_budget = (pending_q.get("expected_answer_type") == ExpectedAnswerType.BUDGET_AMOUNT and (budget_act or extract_explicit_number(text) is not None))
        # Exception: if expected answer is product name/selection and customer names a product or details
        is_answering_product = (pending_q.get("expected_answer_type") == ExpectedAnswerType.PRODUCT_NAME and ("specs" in text or "تفاصيل" in text or "سعر" in text))
        
        if not is_answering_budget and not is_answering_product:
            log.info("Topic change detected! Invalidating pending question.")
            topic_changed = True
            pending_q["resolved"] = True
            pending_q = None

    # 2. Match Dialogue Act and Resolve State
    if greeting_act:
        dialogue_act = DialogueAct.GREETING
    elif extract_explicit_number(text) is not None and any(kw in normalized for kw in ("بـ", "ابو", "سعر", "بكام")):
        dialogue_act = DialogueAct.PRODUCT_REFERENCE
        resolved_value = f"price:{extract_explicit_number(text)}"
    elif cont_act:
        dialogue_act = DialogueAct.CONTINUE
    elif cancel_act:
        dialogue_act = DialogueAct.CANCEL
    elif price_obj_act:
        dialogue_act = DialogueAct.PRICE_OBJECTION
    elif budget_act:
        dialogue_act = DialogueAct.BUDGET
        resolved_budget = extract_explicit_number(text)
    elif pending_q and not pending_q.get("resolved"):
        # Resolve against pending question expected type
        expected_type = pending_q.get("expected_answer_type")
        
        if expected_type == ExpectedAnswerType.YES_NO:
            if yes_act:
                dialogue_act = DialogueAct.YES
                resolved_value = True
                pending_q["resolved"] = True
            elif no_act:
                dialogue_act = DialogueAct.NO
                resolved_value = False
                pending_q["resolved"] = True
            else:
                dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
                
        elif expected_type == ExpectedAnswerType.ONE_OF_OPTIONS:
            options = pending_q.get("options") or []
            
            # Check disjunctive option ambiguity (e.g. YES to a choices list)
            # "اه" or "نعم" or "تمام" when two or more alternatives are present
            if (yes_act or ack_act) and len(options) >= 2:
                dialogue_act = DialogueAct.CLARIFICATION_REQUEST
                clarification_needed = True
                # Format clarification response based on options
                opts_str = " ولا ".join(options)
                clarification_response = f"تمام، تحب {opts_str}؟"
                pending_q["resolved"] = False # Keep active for next turn
            else:
                # Resolve option index or name
                resolved_idx = None
                if "اول" in normalized or "الاول" in normalized or "الأول" in normalized:
                    resolved_idx = 0
                elif "تاني" in normalized or "التاني" in normalized or "الثاني" in normalized:
                    resolved_idx = 1
                elif "تالت" in normalized or "التالت" in normalized or "الثالث" in normalized:
                    resolved_idx = 2
                
                if resolved_idx is not None and resolved_idx < len(options):
                    dialogue_act = DialogueAct.CHOICE
                    resolved_value = options[resolved_idx]
                    pending_q["resolved"] = True
                else:
                    # Match options textually
                    matched_opt = None
                    for opt in options:
                        if normalize_arabic_text(opt) in normalized:
                            matched_opt = opt
                            break
                    if matched_opt:
                        dialogue_act = DialogueAct.CHOICE
                        resolved_value = matched_opt
                        pending_q["resolved"] = True
                    else:
                        dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
                        
        elif expected_type == ExpectedAnswerType.BUDGET_AMOUNT:
            num = extract_explicit_number(text)
            if num is not None:
                dialogue_act = DialogueAct.SHORT_ANSWER
                resolved_value = num
                resolved_budget = num
                pending_q["resolved"] = True
            elif no_act:
                dialogue_act = DialogueAct.NO
                pending_q["resolved"] = True
            else:
                dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
                
        elif expected_type == ExpectedAnswerType.USAGE_DURATION:
            num = extract_explicit_number(text)
            if num is not None:
                dialogue_act = DialogueAct.SHORT_ANSWER
                resolved_value = f"{num} hours"
                pending_q["resolved"] = True
            elif "ساعات" in normalized:
                dialogue_act = DialogueAct.SHORT_ANSWER
                pending_q["resolved"] = True
            else:
                dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
                
        elif expected_type == ExpectedAnswerType.CONTACT:
            phone_match = re.search(r"01[0125]\d{8}", text)
            if phone_match:
                dialogue_act = DialogueAct.SHORT_ANSWER
                resolved_value = phone_match.group(0)
                pending_q["resolved"] = True
            elif no_act:
                dialogue_act = DialogueAct.NO
                pending_q["resolved"] = True
            else:
                dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
                
        elif expected_type == ExpectedAnswerType.FREE_TEXT:
            if len(words := text.split()) >= 1:
                dialogue_act = DialogueAct.SHORT_ANSWER
                resolved_value = text
                pending_q["resolved"] = True
            else:
                dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
                
        else:
            dialogue_act = DialogueAct.UNRESOLVED_DIALOGUE
            
    # 3. Handle Independent Short Replies and Ellipsis Reference Resolution
    if dialogue_act == DialogueAct.UNRESOLVED_DIALOGUE or dialogue_act == DialogueAct.CHOICE:
        # Check explicit indices
        if "الاول" in normalized or "الأول" in normalized:
            dialogue_act = DialogueAct.PRODUCT_SELECTION
            resolved_value = "index:0"
        elif "التاني" in normalized or "الثاني" in normalized:
            dialogue_act = DialogueAct.PRODUCT_SELECTION
            resolved_value = "index:1"
        elif "هو ده" in normalized or "عنه" in normalized or "عليها" in normalized:
            dialogue_act = DialogueAct.PRODUCT_REFERENCE
            resolved_value = "current"
        elif "مش ده" in normalized or "لأ مش ده" in normalized or "قصدي التاني" in normalized:
            dialogue_act = DialogueAct.CANCEL
            # Direct override to ask useful clarification
            override_reply = "فاهمك يا فندم. تحب نقارن بمنتج تاني ولا نراجع فئة تانية تناسب استخدامك؟"
            if pending_q:
                pending_q["resolved"] = True
        elif is_no(text):
            dialogue_act = DialogueAct.NO
            if pending_q:
                pending_q["resolved"] = True
        elif is_yes(text) or ack_act:
            dialogue_act = DialogueAct.ACKNOWLEDGEMENT
            if pending_q:
                pending_q["resolved"] = True
        elif extract_explicit_number(text) is not None and any(kw in normalized for kw in ("بـ", "ابو", "سعر", "بكام")):
            price_val = extract_explicit_number(text)
            dialogue_act = DialogueAct.PRODUCT_REFERENCE
            resolved_value = f"price:{price_val}"
                
    # Persistence belongs to the public-turn atomic boundary.  This resolver
    # may describe a resolution but never commits lead state on its own.

    return {
        "dialogue_act": dialogue_act,
        "resolved_product": resolved_product,
        "resolved_budget": resolved_budget,
        "resolved_value": resolved_value,
        "topic_changed": topic_changed,
        "clarification_needed": clarification_needed,
        "clarification_response": clarification_response,
        "override_reply": override_reply,
        "pending_question": pending_q
    }


def derive_pending_question(reply_text: str, plan_type: str, model_pending: Optional[dict] = None) -> Optional[dict]:
    import uuid
    from datetime import datetime, timezone
    
    pq = {
        "question_id": f"q-{uuid.uuid4().hex[:8]}",
        "source_message_id": None,
        "question_type": plan_type,
        "expected_answer_type": ExpectedAnswerType.FREE_TEXT,
        "options": None,
        "subject": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,
        "resolved": False,
        "resolution_message_id": None
    }
    
    if model_pending and isinstance(model_pending, dict):
        pq["expected_answer_type"] = model_pending.get("expected_answer_type") or pq["expected_answer_type"]
        pq["options"] = model_pending.get("options")
        pq["subject"] = model_pending.get("subject")
        return pq
        
    reply_norm = normalize_arabic_text(reply_text)
    
    if plan_type == "GREETING":
        pq["expected_answer_type"] = ExpectedAnswerType.ONE_OF_OPTIONS
        pq["options"] = ["تسأل عن منتج معين", "أساعدك تختار الأنسب"]
    elif plan_type == "CATEGORY_DISCOVERY":
        if "ساعة" in reply_norm or "يومي" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.USAGE_DURATION
        elif "ميزانية" in reply_norm or "حدود" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.BUDGET_AMOUNT
        else:
            pq["expected_answer_type"] = ExpectedAnswerType.FREE_TEXT
    elif plan_type == "PRODUCT_SELECTION":
        if "مواصفات" in reply_norm and "تقارن" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.ONE_OF_OPTIONS
            pq["options"] = ["أقولك مواصفاته", "نقارنه باختيار تاني"]
        else:
            pq["expected_answer_type"] = ExpectedAnswerType.FREE_TEXT
    elif plan_type == "PRODUCT_PRICE":
        if "تفاصيل" in reply_norm and "تقارن" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.ONE_OF_OPTIONS
            pq["options"] = ["تعرف التفاصيل", "تقارن بينه وبين موديل تاني"]
        else:
            pq["expected_answer_type"] = ExpectedAnswerType.FREE_TEXT
    elif plan_type == "PRICE_OBJECTION":
        if "ميزانيتك" in reply_norm or "حدود كام" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.BUDGET_AMOUNT
        elif "سقف ميزانية" in reply_norm and "بديل بسعر اقل" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.ONE_OF_OPTIONS
            pq["options"] = ["ده سقف ميزانية محدد", "نراجع بديل بسعر أقل"]
        else:
            pq["expected_answer_type"] = ExpectedAnswerType.BUDGET_AMOUNT
    elif plan_type in ("PURCHASE_HANDOFF", "HUMAN_HANDOFF"):
        if "رقم" in reply_norm or "موبايل" in reply_norm or "تواصل" in reply_norm:
            pq["expected_answer_type"] = ExpectedAnswerType.CONTACT
        else:
            pq["expected_answer_type"] = ExpectedAnswerType.FREE_TEXT
            
    return pq
