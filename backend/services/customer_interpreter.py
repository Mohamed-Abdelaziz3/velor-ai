import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence


EMPTY_BRIEF_TEXT = "لا توجد بيانات كافية بعد."

STATE_LABELS = {
    "greeting_only": "تحية فقط",
    "service_discovery": "يستكشف الخدمات",
    "product_interest": "مهتم بمنتج أو خدمة",
    "price_question": "يسأل عن السعر",
    "price_without_context": "يسأل عن السعر بدون تفاصيل كافية",
    "buying_interest": "مهتم مبدئيًا",
    "start_intent": "يسأل عن طريقة البدء",
    "price_objection": "يعترض على السعر",
    "hesitation": "متردد",
    "waiting_for_business": "ينتظر ردًا",
    "human_takeover_pending": "تدخل بشري يحتاج مراجعة",
    "insufficient_data": "لا توجد بيانات كافية",
}

EVIDENCE_LABELS = {
    "price_question": "سأل عن السعر",
    "product_mention": "ذكر منتجًا أو خدمة",
    "objection_price": "اعتراض على السعر",
    "hesitation": "تردد أو تأجيل",
    "urgency": "يريد ردًا سريعًا",
    "start_intent": "يسأل عن طريقة البدء",
    "buying_signal": "أظهر اهتمامًا مبدئيًا",
    "service_inquiry": "سأل عن الخدمات",
    "inquired_about_services": "سأل عن الخدمات",
}

MISSING_DATA_LABELS = {
    "lead_evidence": "إشارات كافية من المحادثة",
    "recent_evidence": "إشارات حديثة من المحادثات",
    "objection_evidence": "اعتراضات واضحة من العملاء",
    "product_context": "بيانات المنتج أو الخدمة",
    "workspace_suggestion": "رد مقترح",
    "product_mention": "المنتج أو الخدمة",
    "normalized_product_name": "اسم المنتج بشكل واضح",
    "latest_customer_message": "رسالة واضحة من العميل",
    "buying_signal": "إشارة اهتمام واضحة",
    "start_intent": "طريقة البدء",
    "price_question": "سؤال واضح عن السعر",
    "lead_id": "العميل",
    "product": "المنتج أو الخدمة",
    "products": "المنتج أو الخدمة",
    "service": "نوع الخدمة",
    "service_type": "نوع الخدمة",
    "need": "الاحتياج",
    "requirements": "متطلبات العميل",
    "current_problem": "المشكلة الحالية",
    "goal": "الهدف المطلوب",
    "budget": "الميزانية",
    "timing": "التوقيت",
    "timeline": "التوقيت",
    "quantity": "الكمية",
    "price": "السعر الموثق",
    "currency": "العملة",
    "objection_reason": "سبب الاعتراض",
    "comparison_options": "البدائل التي يقارن بها",
    "contact_preference": "طريقة التواصل المناسبة",
}

CONFIDENCE_LABELS_AR = {
    "high": "مرتفعة",
    "medium": "متوسطة",
    "low": "منخفضة",
}


@dataclass
class CustomerInterpretation:
    state: str
    state_label: str
    meaning: str
    confidence: str
    confidence_score: float
    missing_data: List[str] = field(default_factory=list)
    important_signals: List[str] = field(default_factory=list)
    next_best_action: str = EMPTY_BRIEF_TEXT
    expected_next: str = EMPTY_BRIEF_TEXT
    safe_suggested_reply: Optional[str] = None
    evidence_summary: List[str] = field(default_factory=list)
    latest_message_sender: Optional[str] = None
    human_takeover: bool = False
    insufficient_data: bool = False
    product_names: List[str] = field(default_factory=list)

    @property
    def confidence_label_ar(self) -> str:
        return CONFIDENCE_LABELS_AR.get(self.confidence, CONFIDENCE_LABELS_AR["low"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "state_label": self.state_label,
            "meaning": self.meaning,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label_ar,
            "missing_data": list(self.missing_data),
            "important_signals": list(self.important_signals),
            "next_best_action": self.next_best_action,
            "expected_next": self.expected_next,
            "safe_suggested_reply": self.safe_suggested_reply,
            "evidence_summary": list(self.evidence_summary),
            "latest_message_sender": self.latest_message_sender,
            "human_takeover": self.human_takeover,
            "insufficient_data": self.insufficient_data,
            "product_names": list(self.product_names),
        }


def safe_json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text)


def _fold_arabic(value: Any) -> str:
    text = normalize_text(value).casefold()
    text = re.sub(r"[إأآا]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    return text


def _strip_punctuation(value: Any) -> str:
    text = _fold_arabic(value)
    text = re.sub(r"[؟?!.,،؛:()[\]{}\"']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_any(text: str, tokens: Iterable[str]) -> bool:
    folded = _fold_arabic(text)
    return any(_fold_arabic(token) in folded for token in tokens)


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    folded = _fold_arabic(text)
    return any(re.search(pattern, folded, re.I) for pattern in patterns)


def humanize_missing_data(items: Optional[Iterable[Any]]) -> List[str]:
    cleaned: List[str] = []
    for item in items or []:
        if item is None:
            continue
        text = normalize_text(item)
        if not text:
            continue
        label = MISSING_DATA_LABELS.get(text.casefold(), text)
        if re.search(r"[a-z]+_[a-z0-9_]+", label, re.I):
            label = "بيانات إضافية من المحادثة"
        if label not in cleaned:
            cleaned.append(label)
    return cleaned


def evidence_label(value: Any) -> str:
    text = normalize_text(value)
    return EVIDENCE_LABELS.get(text.casefold(), text or "إشارة من المحادثة")


def _message_sender(message: Any) -> str:
    sender = normalize_text(getattr(message, "sender", "")).casefold()
    direction = normalize_text(getattr(message, "direction", "")).casefold()
    if direction == "incoming" or sender in {"user", "customer"}:
        return "user"
    if sender in {"assistant", "bot", "velor"}:
        return "assistant"
    if direction == "outgoing" or sender in {"owner", "agent", "human", "manual"}:
        return "owner"
    return sender or "system"


def _message_text(message: Any) -> str:
    return normalize_text(getattr(message, "message", ""))


def _is_greeting_only(value: str) -> bool:
    text = _strip_punctuation(value)
    if not text:
        return False
    without_greeting = re.sub(
        r"\b(السلام عليكم|وعليكم السلام|سلام عليكم|سلام|مرحبا|اهلا|هلا|هاي|صباح الخير|مساء الخير|ازيك|عامل ايه)\b",
        "",
        text,
        flags=re.I,
    ).strip()
    return len(without_greeting) <= 2 and len(text.split()) <= 5


def _is_service_discovery(value: str) -> bool:
    text = _fold_arabic(value)
    if _matches_any(
        text,
        [
            r"خدمات(كم|ك)?",
            r"بتقدم(وا|و|ون)?",
            r"تقدم(وا|و|ون)? ايه",
            r"ايه المتاح",
            r"ماذا تقدم",
            r"ما المتاح",
            r"اعرف خدمات",
            r"what do you offer",
            r"\bservices?\b",
        ],
    ):
        return True
    return bool(
        re.search(r"\bخدمه\b", text)
        and re.search(r"(عايز|محتاج|اريد|احب|حابب|بسال|اعرف|ممكن|ايه|ما|ماذا|؟|\?)", text)
        and not re.search(r"(سيئ|وحش|زفت|مش كويس|رديء)", text)
    )


def _is_price_question(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"سعر",
            r"اسعار",
            r"بكام",
            r"\bكام\b",
            r"تكلفه",
            r"الثمن",
            r"\bprice\b",
            r"\bcost\b",
        ],
    )


def _is_start_intent(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"ابدا ازاي",
            r"ابدأ ازاي",
            r"اشترك ازاي",
            r"اطلب ازاي",
            r"نبدا",
            r"نبدأ",
            r"عايز ابدا",
            r"عايز اشترك",
            r"how (do|can) i start",
            r"subscribe",
            r"sign up",
        ],
    )


def _is_rejection(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"مش\s+مهتم",
            r"مش\s+عايز",
            r"مش\s+عاوز",
            r"مش\s+هشتري",
            r"خلاص\s+مش",
            r"الغاء",
            r"إلغاء",
            r"not\s+interested",
            r"don'?t\s+want",
            r"cancel\s+order",
        ],
    )


def _is_payment_commitment(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"ابعتلي\s+رقم\s+الدفع",
            r"ارسل\s+رقم\s+الدفع",
            r"رقم\s+الحساب",
            r"احول\s+فين",
            r"أحول\s+فين",
            r"أحول\s+على\s+رقم\s+إيه",
            r"send\s+(me\s+)?payment\s+(link|number)",
            r"where\s+do\s+i\s+pay",
            r"how\s+to\s+pay",
            r"هحول\s+دلوقتي",
            r"تمام\s+هات\s+واحد",
            r"عايز\s+اتنين",
            r"عايز\s+2",
            r"عايز\s+3",
            r"أطلب\s+إزاي",
            r"اطلب\s+ازاي",
            r"خلاص\s+هطلب",
        ],
    )


def _is_price_objection(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"غالي",
            r"السعر عالي",
            r"السعر مرتفع",
            r"مكلف",
            r"خصم",
            r"discount",
            r"expensive",
            r"too much",
        ],
    )


def _is_hesitation(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"هفكر",
            r"افكر",
            r"بعدين",
            r"ليس الان",
            r"مش دلوقتي",
            r"ارجعلك",
            r"later",
            r"think about",
            r"not now",
        ],
    )


def _is_buying_interest(value: str) -> bool:
    return _matches_any(
        value,
        [
            r"مهتم",
            r"عايز",
            r"محتاج",
            r"اريد",
            r"ابعت",
            r"احجز",
            r"اطلب",
            r"interested",
            r"i want",
            r"need",
        ],
    )


def _is_waiting_ping(value: str) -> bool:
    text = _strip_punctuation(value)
    if not text:
        return False
    if any(
        detector(value)
        for detector in (
            _is_service_discovery,
            _is_price_question,
            _is_start_intent,
            _is_price_objection,
            _is_hesitation,
        )
    ):
        return False
    if re.search(r"\b(استاذي|أستاذي|حضرتك|لو سمحت|موجود|موجودين|حد هنا|فين الرد|ردوا|ردو|بسرعه|رجاء|معاك)\b", text):
        return True
    return len(text.split()) <= 4 and bool(re.search(r"[؟?]$", normalize_text(value)))


def _clean_product_names(evidence_rows: Sequence[Any], memory: Optional[Any] = None, product_context: Optional[Sequence[Any]] = None, text: str = "") -> List[str]:
    names: List[str] = []
    for row in evidence_rows:
        if normalize_text(getattr(row, "evidence_type", "")) != "product_mention":
            continue
        metadata = safe_json_loads(getattr(row, "metadata_json", None), {})
        name = metadata.get("matched_product_name") or getattr(row, "normalized_value", None)
        if name and normalize_text(name) not in names:
            names.append(normalize_text(name))

    memory_interest = normalize_text(getattr(memory, "product_interest", "")) if memory else ""
    if memory_interest and memory_interest not in names:
        names.append(memory_interest)

    folded_text = _fold_arabic(text)
    for product in product_context or []:
        name = normalize_text(getattr(product, "name", ""))
        aliases = list(getattr(product, "aliases", []) or [])
        candidates = [name, *aliases]
        if name and any(_fold_arabic(candidate) in folded_text for candidate in candidates if normalize_text(candidate)):
            if name not in names:
                names.append(name)

    return names[:3]


def _dedupe(items: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for item in items:
        text = normalize_text(item)
        if text and text not in result:
            result.append(text)
    return result


def _evidence_types(evidence_rows: Sequence[Any]) -> set:
    return {normalize_text(getattr(row, "evidence_type", "")) for row in evidence_rows if normalize_text(getattr(row, "evidence_type", ""))}


def _evidence_summary(evidence_rows: Sequence[Any], fallback_signals: Iterable[str]) -> List[str]:
    summary = []
    for row in evidence_rows[:5]:
        label = evidence_label(getattr(row, "evidence_type", ""))
        value = normalize_text(getattr(row, "normalized_value", ""))
        text = f"{label}: {value}" if value and value != label else label
        summary.append(text)
    summary.extend(fallback_signals)
    return _dedupe(summary)[:5]


def _suggested_reply_for_state(state: str, product_names: Sequence[str], suggestion: Optional[Any]) -> Optional[str]:
    existing = normalize_text(getattr(suggestion, "suggested_reply", "")) if suggestion else ""
    if existing:
        return existing

    product_text = product_names[0] if product_names else "المنتج أو الخدمة"
    replies = {
        "greeting_only": "أهلًا بك، كيف يمكنني مساعدتك اليوم؟",
        "service_discovery": "أكيد، تحب أعرفك خدماتنا بشكل عام، ولا عندك مشكلة معينة محتاج نساعدك فيها؟",
        "price_without_context": "أكيد، ممكن توضح لي المنتج أو الخدمة والكمية أو الاحتياج عشان أقول لك أدق تفاصيل؟",
        "price_question": "أكيد، أقدر أساعدك في السعر. ممكن تحدد الكمية أو الباقة المطلوبة عشان أأكد لك التفاصيل؟",
        "product_interest": f"تمام، أقدر أساعدك في {product_text}. تحب توضح لي الكمية أو الاستخدام المطلوب؟",
        "buying_interest": "تمام، عشان أساعدك بشكل أدق، ممكن توضح لي الخدمة المطلوبة والتوقيت المناسب؟",
        "start_intent": "أكيد، نقدر نبدأ بعد ما توضح الخدمة المطلوبة والتوقيت المناسب لك.",
        "price_objection": "فاهمك. خليني أوضح لك القيمة والاختيارات المتاحة، وهل عندك ميزانية محددة نقارن على أساسها؟",
        "hesitation": "تمام، خذ وقتك. هل في نقطة معينة محتاج أوضحها لك قبل القرار؟",
        "waiting_for_business": "معاك، تحب توضح لي محتاج مساعدة في أي خدمة أو منتج؟",
        "human_takeover_pending": "معاك، راجعت رسالتك. ممكن توضح لي المطلوب عشان أساعدك بدقة؟",
        "insufficient_data": "أهلًا بك، كيف يمكنني مساعدتك اليوم؟",
    }
    return replies.get(state)


def _base_interpretation(
    state: str,
    meaning: str,
    missing_data: Iterable[Any],
    next_best_action: str,
    expected_next: str,
    confidence: str,
    confidence_score: float,
    signals: Iterable[str],
    evidence_rows: Sequence[Any],
    latest_message_sender: Optional[str],
    human_takeover: bool,
    suggestion: Optional[Any],
    product_names: Sequence[str],
    insufficient_data: bool = False,
) -> CustomerInterpretation:
    missing = humanize_missing_data(missing_data)
    important_signals = _dedupe(signals)
    return CustomerInterpretation(
        state=state,
        state_label=STATE_LABELS[state],
        meaning=meaning,
        confidence=confidence,
        confidence_score=max(0.0, min(1.0, confidence_score)),
        missing_data=missing,
        important_signals=important_signals,
        next_best_action=next_best_action,
        expected_next=expected_next,
        safe_suggested_reply=_suggested_reply_for_state(state, product_names, suggestion),
        evidence_summary=_evidence_summary(evidence_rows, important_signals),
        latest_message_sender=latest_message_sender,
        human_takeover=human_takeover,
        insufficient_data=insufficient_data,
        product_names=list(product_names),
    )


def interpret_customer_conversation(
    messages: Optional[Sequence[Any]] = None,
    evidence_rows: Optional[Sequence[Any]] = None,
    suggestion: Optional[Any] = None,
    lead: Optional[Any] = None,
    memory: Optional[Any] = None,
    product_context: Optional[Sequence[Any]] = None,
    company_auto_reply_enabled: Optional[bool] = None,
) -> CustomerInterpretation:
    messages = list(messages or [])
    evidence_rows = list(evidence_rows or [])
    chat_messages = [msg for msg in messages if _message_text(msg)]
    latest_message = chat_messages[-1] if chat_messages else None
    latest_sender = _message_sender(latest_message) if latest_message else None
    customer_texts = [_message_text(msg) for msg in chat_messages if _message_sender(msg) == "user"]
    latest_customer = customer_texts[-1] if customer_texts else ""
    joined_customer = " ".join(customer_texts)
    evidence_types = _evidence_types(evidence_rows)
    product_names = _clean_product_names(evidence_rows, memory=memory, product_context=product_context, text=joined_customer)
    suggestion_missing = safe_json_loads(getattr(suggestion, "missing_data", None), []) if suggestion else []
    lead_paused = bool(getattr(lead, "is_paused", False))
    human_takeover = lead_paused or company_auto_reply_enabled is False
    latest_from_customer = latest_sender == "user"

    if not customer_texts and not evidence_rows and not suggestion:
        return _base_interpretation(
            "insufficient_data",
            "لم تصل رسائل كافية لفهم احتياج العميل بعد.",
            ["latest_customer_message", "service_type", "current_problem"],
            "انتظر رسالة جديدة أو ابدأ بسؤال افتتاحي عند تولّي المحادثة.",
            "نحتاج رسالة من العميل لفهم الاحتياج.",
            "low",
            0.2,
            [],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
            insufficient_data=True,
        )

    if suggestion and not customer_texts and human_takeover:
        return _base_interpretation(
            "human_takeover_pending",
            "المحادثة تحت تولّي بشري ويوجد رد مقترح يحتاج مراجعة قبل الإرسال.",
            [*suggestion_missing, "latest_customer_message"],
            "راجع الرد المقترح وعدّله يدويًا إذا كان مناسبًا.",
            "سيظل الرد التلقائي متوقفًا أثناء التولّي البشري.",
            "medium",
            0.55,
            ["رد مقترح يحتاج مراجعة"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    # Fresh customer behavior takes authority over older historical text
    fresh_customer = latest_customer if latest_customer else joined_customer
    has_rejection = _is_rejection(latest_customer)
    has_payment_commitment = _is_payment_commitment(latest_customer)
    has_price_objection = "objection_price" in evidence_types or _is_price_objection(fresh_customer)
    has_hesitation = "hesitation" in evidence_types or _is_hesitation(fresh_customer)
    has_start = "start_intent" in evidence_types or _is_start_intent(fresh_customer) or has_payment_commitment
    has_price = "price_question" in evidence_types or _is_price_question(fresh_customer)
    has_service = bool(evidence_types & {"service_inquiry", "inquired_about_services"}) or _is_service_discovery(fresh_customer)
    has_buying = "buying_signal" in evidence_types or _is_buying_interest(fresh_customer)
    greeting_only = bool(customer_texts) and all(_is_greeting_only(text) for text in customer_texts)
    waiting_ping = bool(latest_customer and _is_waiting_ping(latest_customer))

    if has_rejection:
        return _base_interpretation(
            "insufficient_data",
            "العميل أظهر عدم رغبة صريحة في الشراء أو الاستمرار.",
            [*suggestion_missing],
            "احترم رغبة العميل وثّق حالة عدم الاهتمام.",
            "لن يتم الضغط على العميل.",
            "high",
            0.92,
            ["عدم رغبة صريحة"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_payment_commitment:
        return _base_interpretation(
            "start_intent",
            "العميل أظهر نية مؤكدة لإتمام الشراء وطلب بيانات الدفع أو خطوات الطلب.",
            [*suggestion_missing, "payment_method"],
            "أرسل بيانات الدفع وسجل طلب العميل فورًا.",
            "في انتظار إتمام خطوة الدفع.",
            "high",
            0.92,
            ["نية شراء صريحة وطلب بيانات الدفع"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_price_objection:
        return _base_interpretation(
            "price_objection",
            "العميل يرى أن السعر مرتفع أو يحتاج تبرير القيمة قبل أي خصم.",
            [*suggestion_missing, "objection_reason", "budget", "comparison_options"],
            "وضّح القيمة والفائدة أولًا، ثم اسأله عن الميزانية أو البدائل التي يقارن بها.",
            "قد يطلب توضيح القيمة أو بديلًا مناسبًا للميزانية.",
            "high" if "objection_price" in evidence_types else "medium",
            0.78 if "objection_price" in evidence_types else 0.62,
            ["اعتراض على السعر"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_hesitation:
        return _base_interpretation(
            "hesitation",
            "العميل متردد أو يؤجل القرار ولا توجد موافقة واضحة بعد.",
            [*suggestion_missing, "objection_reason", "timing", "goal"],
            "اسأله عن النقطة التي تمنعه من القرار وقدم توضيحًا مختصرًا.",
            "قد يوضح سبب التردد أو يطلب وقتًا إضافيًا.",
            "high" if "hesitation" in evidence_types else "medium",
            0.72 if "hesitation" in evidence_types else 0.58,
            ["تردد أو تأجيل"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_start:
        return _base_interpretation(
            "start_intent",
            "العميل يسأل عن طريقة البدء أو الخطوة التالية، وهذا اهتمام مبدئي وليس إغلاقًا مؤكدًا.",
            [*suggestion_missing, "service_type", "requirements", "timing"],
            "اشرح خطوة البدء باختصار واسأله عن الخدمة أو المتطلبات الأساسية.",
            "قد يحدد الخدمة المطلوبة أو يسأل عن السعر والخطوات.",
            "high" if "start_intent" in evidence_types else "medium",
            0.78 if "start_intent" in evidence_types else 0.62,
            ["يسأل عن طريقة البدء"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_price:
        missing = [*suggestion_missing]
        if not product_names:
            missing.extend(["product", "quantity", "need"])
            state = "price_without_context"
            meaning = "العميل مهتم بالتكلفة، لكن السعر يحتاج معرفة المنتج أو الكمية أو الاحتياج."
            next_action = "اسأله عن المنتج أو الكمية قبل عرض السعر."
            expected = "بعد تحديد المنتج أو الكمية يمكن تقديم سعر أدق."
        else:
            missing.append("quantity")
            state = "price_question"
            meaning = "العميل يسأل عن السعر لمنتج أو خدمة مذكورة، لكن لا يجب اختراع أي رقم غير موثق."
            next_action = "راجع السعر من سياق المنتجات/التسعير، واسأل عن الكمية إذا كانت غير واضحة."
            expected = "العميل ينتظر توضيحًا دقيقًا للتكلفة حسب المنتج والكمية."
        return _base_interpretation(
            state,
            meaning,
            missing,
            next_action,
            expected,
            "high" if "price_question" in evidence_types else "medium",
            0.75 if "price_question" in evidence_types else 0.62,
            ["سأل عن السعر"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_service:
        return _base_interpretation(
            "service_discovery",
            "العميل يريد معرفة ما تقدمه ولم يحدد احتياجًا واضحًا بعد.",
            [*suggestion_missing, "service_type", "current_problem", "budget", "timing"],
            "اسأله عن الخدمة أو المشكلة التي يريد حلها.",
            "نحتاج تفاصيل أكثر لتقديم عرض مناسب.",
            "high" if evidence_types & {"service_inquiry", "inquired_about_services"} else "medium",
            0.72 if evidence_types & {"service_inquiry", "inquired_about_services"} else 0.6,
            ["سأل عن الخدمات"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if product_names:
        return _base_interpretation(
            "product_interest",
            f"العميل ذكر منتجًا أو خدمة محددة: {', '.join(product_names)}. لا توجد نية شراء مؤكدة بعد.",
            [*suggestion_missing, "quantity", "budget", "timing"],
            "اسأله عن الكمية أو الاستخدام المطلوب لتحديد الخطوة التالية.",
            "قد يوضح العميل احتياجه أو يسأل عن السعر.",
            "high" if "product_mention" in evidence_types else "medium",
            0.72 if "product_mention" in evidence_types else 0.58,
            [f"ذكر {name}" for name in product_names],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if has_buying:
        return _base_interpretation(
            "buying_interest",
            "العميل يظهر اهتمامًا مبدئيًا حسب البيانات المتاحة، لكن الاحتياج لم يكتمل بعد.",
            [*suggestion_missing, "service_type", "quantity", "budget", "timing"],
            "حوّل الاهتمام إلى سؤال محدد عن الخدمة أو الكمية أو التوقيت.",
            "قد يحدد العميل المطلوب أو يسأل عن السعر.",
            "high" if "buying_signal" in evidence_types else "medium",
            0.7 if "buying_signal" in evidence_types else 0.55,
            ["أظهر اهتمامًا مبدئيًا"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if waiting_ping:
        return _base_interpretation(
            "waiting_for_business",
            "العميل يحاول لفت الانتباه أو ينتظر ردًا أوضح من الفريق.",
            [*suggestion_missing, "service_type", "current_problem", "goal"],
            "رد عليه بسؤال واضح عن احتياجه بدل افتراض السعر أو الخدمة.",
            "قد يوضح العميل المطلوب بعد رد قصير ومباشر.",
            "medium",
            0.55,
            ["ينتظر ردًا"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if greeting_only:
        return _base_interpretation(
            "greeting_only",
            "لا توجد نية شراء واضحة بعد.",
            [*suggestion_missing, "service_type", "current_problem", "budget", "timing"],
            "انتظر رد العميل أو تولَّ المحادثة واسأل سؤالًا افتتاحيًا.",
            "نحتاج رسالة جديدة لفهم الاحتياج.",
            "medium",
            0.55,
            ["تحية فقط"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
        )

    if customer_texts:
        return _base_interpretation(
            "waiting_for_business" if latest_from_customer else "insufficient_data",
            "توجد رسائل من العميل، لكنها لا تحدد احتياجًا أو منتجًا أو نية شراء واضحة بعد.",
            [*suggestion_missing, "service_type", "current_problem", "budget", "timing"],
            "اطلب توضيحًا قصيرًا من العميل عن الخدمة أو المنتج الذي يحتاجه.",
            "نحتاج رسالة أوضح لفهم الاحتياج.",
            "low",
            0.4,
            ["رسالة تحتاج توضيحًا"],
            evidence_rows,
            latest_sender,
            human_takeover,
            suggestion,
            product_names,
            insufficient_data=False,
        )

    return _base_interpretation(
        "insufficient_data",
        "توجد بعض الإشارات المساعدة، لكن لا توجد رسائل كافية لتفسير الاحتياج بثقة.",
        [*suggestion_missing, "latest_customer_message"],
        "انتظر رسالة أوضح من العميل قبل افتراض المنتج أو السعر.",
        "نحتاج تفاعلًا جديدًا من العميل.",
        "low",
        0.35,
        [],
        evidence_rows,
        latest_sender,
        human_takeover,
        suggestion,
        product_names,
        insufficient_data=False,
    )


def render_customer_brief(interpretation: CustomerInterpretation) -> Dict[str, Any]:
    return {
        "what_customer_wants": EMPTY_BRIEF_TEXT if interpretation.insufficient_data else interpretation.state_label,
        "customer_state": interpretation.state_label,
        "latest_signal": interpretation.meaning or EMPTY_BRIEF_TEXT,
        "business_meaning": interpretation.meaning or EMPTY_BRIEF_TEXT,
        "missing_data": interpretation.missing_data,
        "best_next_step": interpretation.next_best_action or EMPTY_BRIEF_TEXT,
        "suggested_reply": interpretation.safe_suggested_reply,
        "expected_next": interpretation.expected_next or EMPTY_BRIEF_TEXT,
        "human_takeover": interpretation.human_takeover,
        "latest_message_sender": interpretation.latest_message_sender,
        "important_signals": interpretation.important_signals,
        "evidence_summary": interpretation.evidence_summary,
        "insufficient_data": interpretation.insufficient_data,
    }


def _question_text(message: str) -> str:
    return _fold_arabic(message)


def classify_lead_question(message: str) -> str:
    text = _question_text(message)
    if _contains_any(text, ["ماذا اقول", "ماذا أقول", "اقول له", "أقول له", "اكتب له", "اكتبلي", "ارد", "أرد", "أفضل رد", "افضل رد", "what should i say", "best reply", "reply for"]):
        return "reply"
    if _contains_any(text, ["مهتم", "فعلا", "فعلًا", "جاد", "نية", "ينفع اقفل", "close", "interested"]):
        return "interest"
    if _contains_any(text, ["بيانات ناقصة", "ناقص", "محتاج اعرف", "missing", "what is missing"]):
        return "missing_data"
    if _contains_any(text, ["السعر", "سعر", "افتح له السعر", "اعرض السعر", "price"]):
        return "price_guidance"
    if _contains_any(text, ["اتولى", "أتولى", "تولي", "human", "manual"]):
        return "takeover"
    if _contains_any(text, ["اهتمامه", "اهتمام", "يريد", "عايز ايه", "عاوز ايه", "main interest"]):
        return "main_interest"
    if _contains_any(text, ["افضل خطوة", "أفضل خطوة", "اعمل ايه", "next step"]):
        return "next_step"
    return "summary"


def render_ask_velor_answer(message: str, interpretation: CustomerInterpretation) -> str:
    intent = classify_lead_question(message)
    missing = "، ".join(interpretation.missing_data) or "لا توجد بيانات ناقصة واضحة"
    signals = "، ".join(interpretation.important_signals or interpretation.evidence_summary) or "لا توجد إشارات قوية بعد"

    if intent == "reply":
        reply = interpretation.safe_suggested_reply or "ممكن توضح لي الخدمة أو المنتج الذي تحتاجه حتى أساعدك بدقة؟"
        return (
            f"اكتب له:\n{reply}\n\n"
            f"السبب: {interpretation.meaning} "
            "هذا رد آمن لأنه يطلب توضيحًا ولا يخترع سعرًا أو منتجًا.\n\n"
            "ملاحظة: الرد مقترح فقط ولم يتم إرساله تلقائيًا."
        )

    if intent == "interest":
        return (
            f"حسب البيانات المتاحة، حالة العميل هي: {interpretation.state_label}.\n\n"
            f"ما يعنيه ذلك: {interpretation.meaning}\n\n"
            f"قوة الدليل: {interpretation.confidence_label_ar}. الدليل الحالي: {signals}.\n"
            "لا أعتبره جاهزًا للشراء إلا إذا ظهرت رسالة أوضح عن المنتج، الكمية، السعر، أو طريقة البدء."
        )

    if intent == "missing_data":
        return (
            f"البيانات الناقصة هي: {missing}.\n\n"
            f"أفضل خطوة الآن: {interpretation.next_best_action}"
        )

    if intent == "price_guidance":
        if interpretation.state in {"price_question", "price_without_context"}:
            return (
                f"{interpretation.state_label}.\n\n"
                f"{interpretation.meaning}\n\n"
                f"قبل فتح السعر، تأكد من: {missing}.\n"
                "لا تعرض رقمًا إلا إذا كان السعر موثقًا في سياق المنتجات/التسعير."
            )
        return (
            "لا أنصح بفتح السعر الآن من غير سؤال واضح عن التكلفة أو منتج محدد.\n\n"
            f"حالة العميل الحالية: {interpretation.state_label}. {interpretation.next_best_action}"
        )

    if intent == "takeover":
        if interpretation.human_takeover:
            return f"المحادثة بالفعل تحت مراجعة/تولّي بشري. أفضل خطوة الآن: {interpretation.next_best_action}"
        return f"لا تحتاج للتولّي إلا إذا أردت الرد يدويًا. حالة العميل: {interpretation.state_label}. {interpretation.next_best_action}"

    if intent == "main_interest":
        return (
            f"اهتمامه الحالي: {interpretation.state_label}.\n\n"
            f"{interpretation.meaning}\n\n"
            f"الإشارات التي أعتمد عليها: {signals}."
        )

    if intent == "next_step":
        return f"أفضل خطوة الآن: {interpretation.next_best_action}\n\nالسبب: {interpretation.meaning}"

    parts = [
        "الخلاصة",
        f"{interpretation.state_label}: {interpretation.meaning}",
        "",
        "ما فهمته من المحادثة",
        interpretation.meaning,
        "",
        "الدليل",
        signals,
        "",
        "مستوى الثقة",
        interpretation.confidence_label_ar,
        "",
        "البيانات الناقصة",
        missing,
        "",
        "أفضل خطوة الآن",
        interpretation.next_best_action,
    ]
    if interpretation.safe_suggested_reply:
        parts.extend(["", "رد مقترح", interpretation.safe_suggested_reply])
    return "\n".join(parts)
