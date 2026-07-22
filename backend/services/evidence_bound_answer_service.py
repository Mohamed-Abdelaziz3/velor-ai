import re
import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

logger = logging.getLogger("adam.evidence_bound_answer")

_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_arabic_digits(text: str) -> str:
    """Converts Arabic-Indic digits (٠-٩) to standard ASCII digits (0-9)."""
    if not text:
        return ""
    return text.translate(_ARABIC_INDIC_DIGITS)


def parse_numeric_val(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    text = normalize_arabic_digits(str(val)).strip()
    if not text:
        return None
    cleaned = re.sub(r"[,\s]", "", text)
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


@dataclass
class EvidenceItem:
    evidence_id: str
    company_id: str
    source_type: str  # "structured_policy" | "curated_knowledge" | "rag_chunk" | "company_prompt" | "lead_memory" | "history" | "customer_input" | "derived_evidence"
    source_id: str
    domain: str       # "return_policy" | "shipping_fee" | "delivery_time" | "opening_hours" | "branch_location" | "payment_methods" | "general"
    claim_key: str
    value: Any
    raw_text: str
    authority_level: int
    freshness_ts: Optional[float] = None
    retrieval_score: float = 1.0


@dataclass
class EvidencePack:
    company_id: str
    query_domains: List[str] = field(default_factory=list)
    supported_facts: Dict[str, EvidenceItem] = field(default_factory=dict)
    unresolved_conflicts: Dict[str, List[EvidenceItem]] = field(default_factory=dict)
    lower_authority_conflicts: Dict[str, List[EvidenceItem]] = field(default_factory=dict)
    insufficient_domains: List[str] = field(default_factory=list)
    context_only_items: List[EvidenceItem] = field(default_factory=list)
    selected_evidence_ids: List[str] = field(default_factory=list)


@dataclass
class EvidenceEnforcementOutcome:
    status: str  # "PASS" | "REPAIRED" | "SAFE_FALLBACK" | "BLOCKED"
    final_answer: str
    violations: List[str] = field(default_factory=list)
    repaired_claims: List[Dict[str, Any]] = field(default_factory=list)
    observability_event: Dict[str, Any] = field(default_factory=dict)


# Authority Levels
AUTHORITY_STRUCTURED_POLICY = 100
AUTHORITY_CURATED_KNOWLEDGE = 90
AUTHORITY_RAG_CHUNK = 70
AUTHORITY_COMPANY_PROMPT = 30
AUTHORITY_LEAD_MEMORY = 20
AUTHORITY_HISTORY = 20
AUTHORITY_CUSTOMER_INPUT = 10
AUTHORITY_DERIVED_INFERENCE = 10


def _generate_evidence_id(company_id: str, source_type: str, domain: str, claim_key: str, value: Any) -> str:
    val_str = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    raw = f"{company_id}|{source_type}|{domain}|{claim_key}|{val_str}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"ev_{company_id}_{source_type}_{digest}"


def detect_query_domains(user_input: str) -> List[str]:
    text = normalize_arabic_digits(user_input or "").lower()
    domains = []
    
    # Return / Refund
    if any(k in text for k in ["استرجاع", "استبدال", "استرداد", "ترجيع", "ارستجاع", "return", "refund", "exchange"]):
        domains.append("return_policy")
        
    # Shipping / Delivery Fee
    if any(k in text for k in ["شحن", "توصيل", "رسوم", "مصاريف", "shipping", "delivery fee"]):
        if any(k in text for k in ["بكام", "كم", "سعر", "رسوم", "تكلفة", "مجاني", "مجانا", "fee", "cost", "free"]):
            domains.append("shipping_fee")
        if any(k in text for k in ["وقت", "مدة", "ساعة", "يوم", "ايام", "أيام", "نوصل", "يوصل", "time", "duration", "days", "hours"]):
            domains.append("delivery_time")
        if "shipping_fee" not in domains and "delivery_time" not in domains:
            domains.extend(["shipping_fee", "delivery_time"])
            
    # Opening Hours
    if any(k in text for k in ["مواعيد", "بتفتح", "بنفتح", "تقفل", "بنقفل", "ساعة", "شغالين", "ساعات العمل", "hours", "open", "close"]):
        domains.append("opening_hours")
        
    # Branch / Location
    if any(k in text for k in ["فرع", "فروع", "عنوان", "مكان", "اسكندرية", "إسكندرية", "القاهرة", "branch", "location", "address"]):
        domains.append("branch_location")
        
    # Payment Methods
    if any(k in text for k in ["دفع", "طريقة الدفع", "كاش", "فيزا", "تقسيط", "أقساط", "اقساط", "payment", "cash", "credit"]):
        domains.append("payment_methods")

    return domains


def parse_evidence_items_from_text(
    company_id: str,
    text: str,
    source_type: str,
    source_id: str,
    authority_level: int,
    freshness_ts: Optional[float] = None,
    retrieval_score: float = 1.0,
) -> List[EvidenceItem]:
    if not text or not text.strip():
        return []

    norm_text = normalize_arabic_digits(text)
    items: List[EvidenceItem] = []

    # 1. Return Policy extraction
    ret_match = re.search(r"(?:الاسترجاع|الاستبدال|الترجيع|الاسترداد|سياسة الاسترجاع|returns?)\s*[^0-9\n]{0,25}?\s*(\d+)\s*(?:يوم|أيام|ايام|يومًا|يومين|days?)", norm_text, re.IGNORECASE)
    if ret_match:
        val_days = int(ret_match.group(1))
        items.append(
            EvidenceItem(
                evidence_id=_generate_evidence_id(company_id, source_type, "return_policy", "return_window_days", val_days),
                company_id=company_id,
                source_type=source_type,
                source_id=source_id,
                domain="return_policy",
                claim_key="return_window_days",
                value=val_days,
                raw_text=ret_match.group(0),
                authority_level=authority_level,
                freshness_ts=freshness_ts,
                retrieval_score=retrieval_score,
            )
        )

    # 2. Shipping Fee extraction
    if re.search(r"الشحن\s*مجاني|التوصيل\s*مجاني|free\s*shipping|free\s*delivery", norm_text, re.IGNORECASE):
        items.append(
            EvidenceItem(
                evidence_id=_generate_evidence_id(company_id, source_type, "shipping_fee", "shipping_fee_egp", 0),
                company_id=company_id,
                source_type=source_type,
                source_id=source_id,
                domain="shipping_fee",
                claim_key="shipping_fee_egp",
                value=0.0,
                raw_text="الشحن مجاني",
                authority_level=authority_level,
                freshness_ts=freshness_ts,
                retrieval_score=retrieval_score,
            )
        )
    else:
        fee_match = re.search(r"(?:رسوم\s*الشحن|مصاريف\s*التوصيل|رسوم\s*التوصيل|سعر\s*الشحن|الشحن|delivery\s*fee|shipping\s*fee)\s*(?:هو|هي|يكون|=|:)?\s*(\d+)\s*(?:جنيه|ج\.م|EGP|LE)?", norm_text, re.IGNORECASE)
        if fee_match:
            fee_val = float(fee_match.group(1))
            items.append(
                EvidenceItem(
                    evidence_id=_generate_evidence_id(company_id, source_type, "shipping_fee", "shipping_fee_egp", fee_val),
                    company_id=company_id,
                    source_type=source_type,
                    source_id=source_id,
                    domain="shipping_fee",
                    claim_key="shipping_fee_egp",
                    value=fee_val,
                    raw_text=fee_match.group(0),
                    authority_level=authority_level,
                    freshness_ts=freshness_ts,
                    retrieval_score=retrieval_score,
                )
            )

    # 3. Delivery Time extraction
    time_match = re.search(r"(?:التوصيل|الشحن|مدة التوصيل|وقت التوصيل|delivery|shipping)\s*(?:خلال|في خلال|في غضون|بياخد|within)?\s*(\d+(?:\s*-\s*\d+)?)\s*(ساعة|ساعات|يوم|أيام|ايام|hours?|days?)", norm_text, re.IGNORECASE)
    if time_match:
        time_val = f"{time_match.group(1)} {time_match.group(2)}"
        items.append(
            EvidenceItem(
                evidence_id=_generate_evidence_id(company_id, source_type, "delivery_time", "delivery_time_text", time_val),
                company_id=company_id,
                source_type=source_type,
                source_id=source_id,
                domain="delivery_time",
                claim_key="delivery_time_text",
                value=time_val,
                raw_text=time_match.group(0),
                authority_level=authority_level,
                freshness_ts=freshness_ts,
                retrieval_score=retrieval_score,
            )
        )

    # 4. Opening Hours extraction
    hours_match = re.search(r"(?:مواعيد العمل|ساعات العمل|مواعيد|بنفتح|working hours|open hours)\s*[:\sمن]*(\d{1,2}(?::\d{2})?\s*(?:ص|م|am|pm)?\s*(?:إلى|لـ|-|to)\s*\d{1,2}(?::\d{2})?\s*(?:ص|م|am|pm)?)", norm_text, re.IGNORECASE)
    if hours_match:
        hours_val = hours_match.group(1).strip()
        items.append(
            EvidenceItem(
                evidence_id=_generate_evidence_id(company_id, source_type, "opening_hours", "opening_hours_text", hours_val),
                company_id=company_id,
                source_type=source_type,
                source_id=source_id,
                domain="opening_hours",
                claim_key="opening_hours_text",
                value=hours_val,
                raw_text=hours_match.group(0),
                authority_level=authority_level,
                freshness_ts=freshness_ts,
                retrieval_score=retrieval_score,
            )
        )

    # 5. Branch Location extraction
    branch_match = re.search(r"(?:فرعنا|فروعنا|فروع|فرع|branch|branches)\s*(?:في|:)?\s*([^\n\.]+)", norm_text, re.IGNORECASE)
    if branch_match:
        b_text = branch_match.group(1).strip()
        cities = []
        if any(c in b_text for c in ["القاهرة", "cairo"]):
            cities.append("cairo")
        if any(c in b_text for c in ["الجيزة", "giza"]):
            cities.append("giza")
        if any(c in b_text for c in ["اسكندرية", "إسكندرية", "alexandria", "alex"]):
            cities.append("alexandria")
        if cities:
            items.append(
                EvidenceItem(
                    evidence_id=_generate_evidence_id(company_id, source_type, "branch_location", "branch_cities", sorted(cities)),
                    company_id=company_id,
                    source_type=source_type,
                    source_id=source_id,
                    domain="branch_location",
                    claim_key="branch_cities",
                    value=sorted(cities),
                    raw_text=branch_match.group(0),
                    authority_level=authority_level,
                    freshness_ts=freshness_ts,
                    retrieval_score=retrieval_score,
                )
            )

    # 6. Payment Methods extraction
    pay_match = re.search(r"(?:الدفع|طريقة الدفع|طرق الدفع|payment)\s*(?:عن طريق|:)?\s*([^\n\.]+)", norm_text, re.IGNORECASE)
    if pay_match:
        p_text = pay_match.group(1).strip()
        methods = []
        if any(m in p_text for m in ["كاش", "نقدا", "نقدًا", "cash"]):
            methods.append("cash")
        if any(m in p_text for m in ["فيزا", "بطاقة", "كارت", "credit", "card"]):
            methods.append("card")
        if any(m in p_text for m in ["تقسيط", "أقساط", "اقساط", "installment"]):
            methods.append("installment")
        if methods:
            items.append(
                EvidenceItem(
                    evidence_id=_generate_evidence_id(company_id, source_type, "payment_methods", "accepted_payments", sorted(methods)),
                    company_id=company_id,
                    source_type=source_type,
                    source_id=source_id,
                    domain="payment_methods",
                    claim_key="accepted_payments",
                    value=sorted(methods),
                    raw_text=pay_match.group(0),
                    authority_level=authority_level,
                    freshness_ts=freshness_ts,
                    retrieval_score=retrieval_score,
                )
            )

    return items


def build_evidence_pack(
    company_id: str,
    user_input: str,
    company_data: Dict[str, Any],
    rag_chunks: Optional[List[str]] = None,
    lead_memory_text: Optional[str] = None,
    history_messages: Optional[List[Dict[str, Any]]] = None,
) -> EvidencePack:
    query_domains = detect_query_domains(user_input)
    all_items: List[EvidenceItem] = []

    # Source B/C: Structured Knowledge / Knowledge Base
    kb_text = str(company_data.get("knowledge_base") or "")
    if kb_text:
        kb_items = parse_evidence_items_from_text(
            company_id=company_id,
            text=kb_text,
            source_type="curated_knowledge",
            source_id="kb_main",
            authority_level=AUTHORITY_CURATED_KNOWLEDGE,
        )
        all_items.extend(kb_items)

    # Source D: RAG Chunks
    if rag_chunks:
        for idx, chunk in enumerate(rag_chunks):
            chunk_items = parse_evidence_items_from_text(
                company_id=company_id,
                text=chunk,
                source_type="rag_chunk",
                source_id=f"rag_chunk_{idx}",
                authority_level=AUTHORITY_RAG_CHUNK,
                retrieval_score=1.0 - (idx * 0.05),
            )
            all_items.extend(chunk_items)

    # Source E: Company Prompt (Context-Only)
    sp_text = str(company_data.get("system_prompt") or "")
    if sp_text:
        sp_items = parse_evidence_items_from_text(
            company_id=company_id,
            text=sp_text,
            source_type="company_prompt",
            source_id="prompt_main",
            authority_level=AUTHORITY_COMPANY_PROMPT,
        )
        all_items.extend(sp_items)

    # Source F: Lead Memory (Context-Only)
    if lead_memory_text:
        mem_items = parse_evidence_items_from_text(
            company_id=company_id,
            text=lead_memory_text,
            source_type="lead_memory",
            source_id="lead_memory",
            authority_level=AUTHORITY_LEAD_MEMORY,
        )
        all_items.extend(mem_items)

    # Source G: History (Context-Only)
    if history_messages:
        hist_text = " ".join([str(m.get("content") or "") for m in history_messages])
        hist_items = parse_evidence_items_from_text(
            company_id=company_id,
            text=hist_text,
            source_type="history",
            source_id="conversation_history",
            authority_level=AUTHORITY_HISTORY,
        )
        all_items.extend(hist_items)

    # Source H: Customer Input (Context-Only)
    cust_items = parse_evidence_items_from_text(
        company_id=company_id,
        text=user_input,
        source_type="customer_input",
        source_id="user_message",
        authority_level=AUTHORITY_CUSTOMER_INPUT,
    )
    all_items.extend(cust_items)

    pack = EvidencePack(company_id=company_id, query_domains=query_domains)

    # Domain-Aware Conflict Resolution
    domain_groups: Dict[str, List[EvidenceItem]] = {}
    for item in all_items:
        if item.authority_level < 70:
            pack.context_only_items.append(item)
        else:
            domain_groups.setdefault(item.domain, []).append(item)

    for domain, items in domain_groups.items():
        max_auth = max(i.authority_level for i in items)
        top_auth_items = [i for i in items if i.authority_level == max_auth]
        lower_auth_items = [i for i in items if i.authority_level < max_auth]

        unique_values = {}
        for item in top_auth_items:
            val_key = json.dumps(item.value, sort_keys=True)
            unique_values.setdefault(val_key, []).append(item)

        if len(unique_values) == 1:
            winner = top_auth_items[0]
            pack.supported_facts[domain] = winner
            pack.selected_evidence_ids.append(winner.evidence_id)

            for l_item in lower_auth_items:
                if json.dumps(l_item.value, sort_keys=True) != json.dumps(winner.value, sort_keys=True):
                    pack.lower_authority_conflicts.setdefault(domain, []).append(l_item)

        else:
            freshness_resolved = False
            items_with_ts = [i for i in top_auth_items if i.freshness_ts is not None]
            if len(items_with_ts) == len(top_auth_items) and len(items_with_ts) > 1:
                items_with_ts.sort(key=lambda x: x.freshness_ts, reverse=True)
                if items_with_ts[0].freshness_ts > items_with_ts[1].freshness_ts:
                    winner = items_with_ts[0]
                    pack.supported_facts[domain] = winner
                    pack.selected_evidence_ids.append(winner.evidence_id)
                    freshness_resolved = True

            if not freshness_resolved:
                pack.unresolved_conflicts[domain] = top_auth_items
                logger.info("[EVIDENCE_CONFLICT] Equal-authority unresolved conflict in domain '%s' for company '%s'", domain, company_id)

    for q_dom in query_domains:
        if q_dom not in pack.supported_facts and q_dom not in pack.unresolved_conflicts:
            pack.insufficient_domains.append(q_dom)

    return pack


def enforce_evidence_bound_answer(
    user_input: str,
    candidate_reply: str,
    company_id: str,
    company_data: Dict[str, Any],
    rag_chunks: Optional[List[str]] = None,
    lead_memory_text: Optional[str] = None,
    history_messages: Optional[List[Dict[str, Any]]] = None,
    model_evidence_ids: Optional[List[str]] = None,
) -> EvidenceEnforcementOutcome:
    if not candidate_reply or not candidate_reply.strip():
        return EvidenceEnforcementOutcome(
            status="PASS",
            final_answer=candidate_reply,
            observability_event={"outcome": "PASS", "violations": []},
        )

    pack = build_evidence_pack(
        company_id=company_id,
        user_input=user_input,
        company_data=company_data,
        rag_chunks=rag_chunks,
        lead_memory_text=lead_memory_text,
        history_messages=history_messages,
    )

    norm_reply = normalize_arabic_digits(candidate_reply)
    working_reply = norm_reply
    violations: List[str] = []
    repaired_claims: List[Dict[str, Any]] = []

    # 0. Validate Evidence Reference IDs if provided
    if model_evidence_ids:
        all_valid_ids = set(pack.selected_evidence_ids + [item.evidence_id for item in pack.context_only_items])
        for eid in model_evidence_ids:
            if not eid.startswith("ev_") or eid not in all_valid_ids or company_id not in eid:
                violations.append("invalid_or_cross_tenant_evidence_id")
                fallback_text = "عذرًا، الإجابة غير مدعومة بأدلة موثوقة من الشركة."
                return EvidenceEnforcementOutcome(
                    status="SAFE_FALLBACK",
                    final_answer=fallback_text,
                    violations=violations,
                    observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                )

    # 1. RETURN POLICY ENFORCEMENT
    ret_claim = re.search(r"(?:الاسترجاع|الاستبدال|الترجيع|الاسترداد|سياسة الاسترجاع|returns?)\s*[^0-9\n]{0,25}?\s*(\d+)\s*(?:يوم|أيام|ايام|يومًا|يومين|days?)", norm_reply, re.IGNORECASE)
    if not ret_claim:
        ret_claim = re.search(r"\b(\d+)\s*(?:يوم|أيام|ايام|يومًا|days?)\s*(?:استرجاع|استبدال|ترجيع)", norm_reply, re.IGNORECASE)

    if ret_claim:
        claimed_days = int(ret_claim.group(1))
        domain = "return_policy"

        if domain in pack.supported_facts:
            supported_item = pack.supported_facts[domain]
            supported_days = int(supported_item.value)
            if claimed_days != supported_days:
                violations.append("wrong_return_window_claim")
                working_reply = re.sub(
                    rf"\b{claimed_days}\b\s*(?:يوم|أيام|ايام|يومًا|days?)",
                    f"{supported_days} يوم",
                    working_reply,
                    flags=re.IGNORECASE,
                )
                repaired_claims.append({
                    "domain": domain,
                    "type": "repaired_return_window",
                    "from": claimed_days,
                    "to": supported_days,
                })
        elif domain in pack.unresolved_conflicts:
            violations.append("unresolved_return_policy_conflict")
            fallback_text = "عندي تعارض في بيانات سياسة الاسترجاع الحالية، فمش هأكد رقم غير موثوق."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )
        else:
            violations.append("unsupported_return_policy_invented")
            fallback_text = "ما عنديش سياسة استرجاع موثوقة أقدر أكدها دلوقتي."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 2. SHIPPING FEE ENFORCEMENT
    has_free_claim = bool(re.search(r"الشحن\s*مجاني|التوصيل\s*مجاني|free\s*shipping|free\s*delivery", norm_reply, re.IGNORECASE))
    fee_match = re.search(r"(?:رسوم\s*الشحن|مصاريف\s*التوصيل|رسوم\s*التوصيل|سعر\s*الشحن|الشحن|delivery\s*fee|shipping\s*fee)\s*(?:هو|هي|يكون|=|:)?\s*(\d+)\s*(?:جنيه|ج\.م|EGP|LE)?", norm_reply, re.IGNORECASE)
    
    if has_free_claim or fee_match:
        domain = "shipping_fee"
        claimed_fee = 0.0 if has_free_claim else float(fee_match.group(1))

        if domain in pack.supported_facts:
            supported_item = pack.supported_facts[domain]
            supported_fee = float(supported_item.value)
            if abs(claimed_fee - supported_fee) > 0.01:
                violations.append("wrong_shipping_fee_claim")
                if supported_fee == 0:
                    working_reply = "الشحن مجاني."
                else:
                    target_fee_str = f"{supported_fee:.0f}" if supported_fee.is_integer() else f"{supported_fee:.2f}"
                    if has_free_claim:
                        working_reply = working_reply.replace("الشحن مجاني", f"رسوم الشحن {target_fee_str} جنيه").replace("التوصيل مجاني", f"رسوم الشحن {target_fee_str} جنيه")
                    elif fee_match:
                        working_reply = working_reply.replace(fee_match.group(1), target_fee_str)
                repaired_claims.append({
                    "domain": domain,
                    "type": "repaired_shipping_fee",
                    "from": claimed_fee,
                    "to": supported_fee,
                })
        elif domain in pack.unresolved_conflicts:
            violations.append("unresolved_shipping_fee_conflict")
            fallback_text = "عندي تعارض في بيانات رسوم التوصيل الحالية، فمش هأكد رقم غير موثوق."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )
        else:
            violations.append("unsupported_shipping_fee_invented")
            fallback_text = "رسوم الشحن غير محددة بشكل موثوق حالياً."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 3. DELIVERY TIME ENFORCEMENT
    delivery_claim = re.search(r"(?:التوصيل|الشحن|مدة التوصيل|وقت التوصيل|delivery|shipping)\s*(?:خلال|في خلال|في غضون|بياخد|within)?\s*(\d+(?:\s*-\s*\d+)?)\s*(ساعة|ساعات|يوم|أيام|ايام|hours?|days?)", norm_reply, re.IGNORECASE)
    if delivery_claim:
        domain = "delivery_time"
        if domain in pack.supported_facts:
            supported_item = pack.supported_facts[domain]
            supported_val = str(supported_item.value)
            claimed_val = f"{delivery_claim.group(1)} {delivery_claim.group(2)}"
            if claimed_val != supported_val:
                violations.append("wrong_delivery_time_claim")
                working_reply = working_reply.replace(delivery_claim.group(0), f"التوصيل خلال {supported_val}")
                repaired_claims.append({
                    "domain": domain,
                    "type": "repaired_delivery_time",
                    "from": claimed_val,
                    "to": supported_val,
                })
        elif domain in pack.unresolved_conflicts:
            violations.append("unresolved_delivery_time_conflict")
            fallback_text = "عندي تعارض في بيانات مدة التوصيل الحالية، فمش هأكد رقم غير موثوق."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )
        else:
            violations.append("unsupported_delivery_time_invented")
            fallback_text = "ما عنديش مدة توصيل موثوقة أقدر أكدها دلوقتي."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 4. OPENING HOURS ENFORCEMENT
    hours_claim = re.search(r"(?:بنفتح|بنقفل|مواعيدنا|open|close)\s*[:\sالساعة]*(\d{1,2}(?::\d{2})?)", norm_reply, re.IGNORECASE)
    if hours_claim:
        domain = "opening_hours"
        if domain in pack.supported_facts:
            supported_item = pack.supported_facts[domain]
            supported_hours = str(supported_item.value)
            if "10" in hours_claim.group(1) and "10" not in supported_hours:
                violations.append("wrong_opening_hours_claim")
                fallback_text = f"مواعيد العمل المعتمدة لدينا هي: {supported_hours}."
                return EvidenceEnforcementOutcome(
                    status="SAFE_FALLBACK",
                    final_answer=fallback_text,
                    violations=violations,
                    observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                )
        elif domain in pack.unresolved_conflicts:
            violations.append("unresolved_opening_hours_conflict")
            fallback_text = "عندي تعارض في بيانات مواعيد العمل الحالية، فمش هأكد رقم غير موثوق."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )
        else:
            violations.append("unsupported_opening_hours_invented")
            fallback_text = "مواعيد العمل غير محددة بشكل موثوق حالياً."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 5. BRANCH LOCATION & NEGATIVE CLAIM SAFETY ENFORCEMENT
    if any(k in user_input for k in ["اسكندرية", "إسكندرية", "alexandria"]):
        domain = "branch_location"
        is_claiming_alex_branch = bool(re.search(r"(?:أيوه|ايوه|نعم|عندنا|فرعنا|موجود)\s*(?:فرع)?\s*(?:في|ف)?\s*(?:اسكندرية|إسكندرية|alexandria)", norm_reply, re.IGNORECASE))
        if is_claiming_alex_branch:
            if domain in pack.supported_facts:
                cities = pack.supported_facts[domain].value
                if "alexandria" not in cities:
                    violations.append("invented_branch_location")
                    fallback_text = "مش لاقي عندي دليل موثوق على وجود فرع في اسكندرية."
                    return EvidenceEnforcementOutcome(
                        status="SAFE_FALLBACK",
                        final_answer=fallback_text,
                        violations=violations,
                        observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                    )
            else:
                violations.append("unsupported_branch_location_invented")
                fallback_text = "مش لاقي عندي دليل موثوق على وجود فرع في اسكندرية."
                return EvidenceEnforcementOutcome(
                    status="SAFE_FALLBACK",
                    final_answer=fallback_text,
                    violations=violations,
                    observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                )

    # 6. PAYMENT METHODS ENFORCEMENT
    pay_claim = re.search(r"(?:الدفع|طريقة الدفع|طرق الدفع)\s*(?:كاش|فيزا|تقسيط|نقدا|كاش فقط)", norm_reply, re.IGNORECASE)
    if pay_claim:
        domain = "payment_methods"
        if domain in pack.supported_facts:
            supported_methods = pack.supported_facts[domain].value
            if "cash" in pay_claim.group(0) and "cash" not in supported_methods:
                violations.append("wrong_payment_method_claim")
                fallback_text = "طرق الدفع غير المذكورة غير معتمدة حالياً."
                return EvidenceEnforcementOutcome(
                    status="SAFE_FALLBACK",
                    final_answer=fallback_text,
                    violations=violations,
                    observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                )
        elif domain in pack.unresolved_conflicts:
            violations.append("unresolved_payment_methods_conflict")
            fallback_text = "عندي تعارض في بيانات طرق الدفع الحالية، فمش هأكد رقم غير موثوق."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )
        elif "payment_methods" in pack.query_domains and domain not in pack.supported_facts:
            violations.append("unsupported_payment_methods_invented")
            fallback_text = "طرق الدفع غير محددة بشكل موثوق حالياً."
            return EvidenceEnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # Digit normalization check
    if not repaired_claims and working_reply != candidate_reply:
        # The only difference was digit normalization e.g. ١٤ -> 14
        return EvidenceEnforcementOutcome(
            status="PASS",
            final_answer=candidate_reply,
            violations=violations,
            repaired_claims=[],
            observability_event={
                "outcome": "PASS",
                "violations": [],
                "selected_evidence_ids": pack.selected_evidence_ids,
            },
        )

    if repaired_claims or working_reply != candidate_reply:
        return EvidenceEnforcementOutcome(
            status="REPAIRED",
            final_answer=working_reply,
            violations=violations,
            repaired_claims=repaired_claims,
            observability_event={
                "outcome": "REPAIRED",
                "violations": violations,
                "selected_evidence_ids": pack.selected_evidence_ids,
            },
        )

    return EvidenceEnforcementOutcome(
        status="PASS",
        final_answer=candidate_reply,
        violations=violations,
        observability_event={
            "outcome": "PASS",
            "violations": [],
            "selected_evidence_ids": pack.selected_evidence_ids,
        },
    )
