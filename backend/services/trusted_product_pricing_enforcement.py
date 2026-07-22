import re
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services.product_context_service import ProductContext

logger = logging.getLogger("adam.pricing_enforcement")

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
class EnforcementOutcome:
    status: str  # "PASS" | "REPAIRED" | "SAFE_FALLBACK" | "BLOCKED"
    final_answer: str
    violations: List[str] = field(default_factory=list)
    repaired_claims: List[Dict[str, Any]] = field(default_factory=list)
    observability_event: Dict[str, Any] = field(default_factory=dict)


_CURRENCY_TOKENS_EGP = ["جنيه", "ج.م", "جنيهات", "جم", "egp", "le"]
_CURRENCY_TOKENS_USD = ["usd", "$", "دولار", "دولارات"]
_CURRENCY_TOKENS_EUR = ["eur", "يورو", "€"]


def _detect_currency(text: str) -> Optional[str]:
    lower = text.lower()
    for token in _CURRENCY_TOKENS_USD:
        if token in lower:
            return "USD"
    for token in _CURRENCY_TOKENS_EUR:
        if token in lower:
            return "EUR"
    for token in _CURRENCY_TOKENS_EGP:
        if token in lower:
            return "EGP"
    return None


def _extract_price_claims_with_context(
    text: str,
    all_products: List[ProductContext],
) -> List[Dict[str, Any]]:
    """
    Extracts explicit price/money mentions from text, binding them to product context
    while avoiding false positives on model numbers (e.g. FocusDesk 120), quantities, warranty years, etc.
    """
    norm_text = normalize_arabic_digits(text)

    model_numbers = set()
    for p in all_products:
        nums = re.findall(r"\b\d+\b", p.name)
        for n in nums:
            model_numbers.add(n)
        if p.sku:
            sku_nums = re.findall(r"\b\d+\b", p.sku)
            for n in sku_nums:
                model_numbers.add(n)

    claims = []
    seen_spans = set()

    # Pattern 1: Number with explicit currency token (e.g. "6900 جنيه", "6,900 EGP", "6900 USD")
    p1 = r"(\d+(?:[,\s]\d{3})*(?:\.\d+)?|\d+)\s*(جنيه|ج\.م|جنيهات|EGP|USD|دولار|EUR|يورو|\$)"
    for m in re.finditer(p1, norm_text, re.IGNORECASE):
        span = m.span()
        num_str = m.group(1).strip()
        curr_str = _detect_currency(m.group(2))
        val = parse_numeric_val(num_str)
        if val is not None:
            seen_spans.add(span)
            claims.append({
                "raw": m.group(0),
                "value": val,
                "currency": curr_str or "EGP",
                "span": span,
                "num_str": num_str,
            })

    # Pattern 2: Price indicator keyword followed by text and a number (e.g. "سعر Ergo One هو 6500", "سعره 6500", "بـ 6500", "costs 6500", "الإجمالي 12000")
    p2 = r"(?:سعر(?:ه|ها)?|بـ|سعر|بـسعر|تكلفة|تكلفته|قيمت(?:ه|ها)|بقيمـة|بمبلغ|المجموع|الإجمالي|الاجمالي|total|price|costs)\s*([^0-9\n]{0,30}?)\s*(\$|EGP|USD|EUR)?\s*(\d+(?:[,\s]\d{3})*(?:\.\d+)?|\d+)"
    for m in re.finditer(p2, norm_text, re.IGNORECASE):
        span = m.span()
        if any(s[0] <= span[0] and span[1] <= s[1] for s in seen_spans):
            continue
        num_str = m.group(3).strip()
        curr_str = _detect_currency(m.group(2) or "")
        val = parse_numeric_val(num_str)
        if val is None:
            continue
        if len(num_str) == 11 and num_str.startswith("01"):
            continue
        seen_spans.add(span)
        claims.append({
            "raw": m.group(0),
            "value": val,
            "currency": curr_str or "EGP",
            "span": span,
            "num_str": num_str,
        })

    return claims


def _check_installment_policy(company_knowledge: Optional[Dict[str, Any]]) -> bool:
    if not company_knowledge:
        return False
    kb = str(company_knowledge.get("knowledge_base") or "")
    sp = str(company_knowledge.get("system_prompt") or "")
    combined = (kb + " " + sp).lower()
    installment_keywords = ["تقسيط", "أقساط", "اقساط", "دفعة مقدمة", "مقدم", "شروط التقسيط", "installment", "installments"]
    return any(kw in combined for kw in installment_keywords)


def _catalog_grounded_multi_product_answer(resolved_products: List[Dict[str, Any]]) -> str:
    lines = []
    for product in resolved_products:
        name = product.get("name")
        if not name:
            continue

        price = product.get("price")
        currency = product.get("currency") or "EGP"
        if price is None:
            price_text = "price unavailable in trusted catalog"
        else:
            try:
                price_float = float(price)
                price_num = f"{price_float:.0f}" if price_float.is_integer() else f"{price_float:.2f}"
            except (TypeError, ValueError):
                price_num = str(price)
            price_text = f"{price_num} {currency}"

        facts = [f"{name}: {price_text}"]
        description = product.get("description")
        if description:
            facts.append(str(description))
        warranty = product.get("warranty")
        if warranty:
            facts.append(f"warranty: {warranty}")
        stock = product.get("stock")
        if stock is not None:
            facts.append(f"stock: {stock}")
        lines.append(" - ".join(facts[:4]))

    if not lines:
        return "I can only confirm product details from the trusted catalog, and no trusted product match is available."
    return "Trusted catalog comparison: " + " | ".join(lines)


def enforce_trusted_product_and_pricing(
    user_input: str,
    candidate_reply: str,
    resolved_context: Dict[str, Any],
    all_products: List[ProductContext],
    company_knowledge: Optional[Dict[str, Any]] = None,
) -> EnforcementOutcome:
    if not candidate_reply or not candidate_reply.strip():
        return EnforcementOutcome(
            status="PASS",
            final_answer=candidate_reply,
            observability_event={"outcome": "PASS", "violations": []},
        )

    norm_reply = normalize_arabic_digits(candidate_reply)
    reply_lower = norm_reply.lower()

    status = resolved_context.get("status", "empty")
    resolved_products = resolved_context.get("resolved_products", [])
    candidates = resolved_context.get("candidates", [])
    catalog_summary = resolved_context.get("catalog_summary", {})

    # If resolved_products is empty, try resolving from candidate_reply or all_products
    if not resolved_products and all_products and status not in ["not_found", "ambiguous"]:
        for p in all_products:
            if p.name.lower() in reply_lower or p.name.replace("Arvena ", "").lower() in reply_lower:
                resolved_products.append(p.to_delivery_dict())

    violations = []
    repaired_claims = []

    # 1. Check for UNKNOWN PRODUCT Invention
    if status == "not_found":
        price_claims = _extract_price_claims_with_context(norm_reply, all_products)
        if price_claims:
            violations.append("unknown_product_claim")
            all_names = catalog_summary.get("all_product_names", [])
            names_str = f" المتاح لدينا: {', '.join(all_names)}" if all_names else ""
            fallback_text = f"عذرًا، المنتج المطلوب غير متوفر حاليًا في الكتالوج الموثوق.{names_str}"
            return EnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 2. Check for AMBIGUOUS PRODUCT Claim Fabrication
    if status == "ambiguous":
        price_claims = _extract_price_claims_with_context(norm_reply, all_products)
        is_asking_clarification = any(token in reply_lower for token in ["تقصد", "أنهي", "انهي", "أيها", "ايها", "ولا", "which", "model"])
        if price_claims and not is_asking_clarification:
            violations.append("ambiguous_product_claim")
            cand_names = [c.get("name") for c in candidates if c.get("name")]
            names_str = " أو ".join(cand_names) if cand_names else "المنتجات المتاحة"
            fallback_text = f"عندنا أكثر من موديل ({names_str}). تحب تعرف سعر أي موديل بالتحديد؟"
            return EnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 3. Check for UNSUPPORTED INSTALLMENT / PAYMENT TERMS
    installment_patterns = [
        r"(\d+٪|\d+%|\d+\s*بالمائة)\s*(مقدم|دفعة مقدمة)",
        r"(تقسيط|أقساط|اقساط)\s*(على|خلال)?\s*\d+\s*(أشهر|شهور|شهر|months|month)",
        r"الباقي\s*بعد\s*\d+\s*(أشهر|شهور|شهر)",
        r"50%\s*مقدم",
    ]
    has_installment_claim = any(re.search(pat, norm_reply, re.IGNORECASE) for pat in installment_patterns)
    if has_installment_claim:
        has_policy = _check_installment_policy(company_knowledge)
        if not has_policy:
            violations.append("unsupported_installment_terms")
            fallback_text = "ما عنديش شروط تقسيط موثوقة أقدر أأكدها حاليًا."
            return EnforcementOutcome(
                status="SAFE_FALLBACK",
                final_answer=fallback_text,
                violations=violations,
                observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
            )

    # 4. Check for UNSUPPORTED DISCOUNTS
    has_structured_discount = False
    for rp in resolved_products:
        if rp.get("quantity_discounts"):
            has_structured_discount = True
            break
    if not has_structured_discount:
        for p in all_products:
            if p.quantity_discounts:
                has_structured_discount = True
                break

    discount_claim_patterns = [
        r"(وهعملك|خصم|تخفيض|discount)\s*(خصم|تخفيض|بقيمة)?\s*(\d+٪|\d+%)",
        r"لو\s*خدت\s*\d+\s*هعملك\s*خصم\s*\d+٪?",
    ]

    has_discount_claim = any(re.search(pat, norm_reply, re.IGNORECASE) for pat in discount_claim_patterns)
    if has_discount_claim:
        claimed_pct_match = re.search(r"(\d+)(?:٪|%)", norm_reply)
        claimed_pct = float(claimed_pct_match.group(1)) if claimed_pct_match else None

        qty_match = re.search(r"(\d+)\s*(×|\*|من|قطعة|قطع|وحدات|units|pieces)?", user_input)
        claimed_qty = 1
        if qty_match:
            try:
                claimed_qty = int(qty_match.group(1))
            except ValueError:
                claimed_qty = 1

        is_valid_discount = False
        if has_structured_discount and claimed_pct is not None:
            for rp in resolved_products:
                q_discounts = rp.get("quantity_discounts") or []
                for qd in q_discounts:
                    min_q = qd.get("min_quantity") or qd.get("min_qty") or 1
                    pct = qd.get("discount_percent") or qd.get("discount") or 0
                    if claimed_qty >= min_q and abs(claimed_pct - float(pct)) < 0.01:
                        is_valid_discount = True
                        break

        if not is_valid_discount:
            violations.append("unsupported_discount")
            reply_without_discount = norm_reply
            for pat in discount_claim_patterns:
                reply_without_discount = re.sub(pat, "", reply_without_discount, flags=re.IGNORECASE)
            reply_without_discount = re.sub(r"\s+", " ", reply_without_discount).strip()
            if len(reply_without_discount) < 10:
                fallback_text = "الأسعار الموضحة هي الأسعار النهائية المعتمدة حاليًا."
                return EnforcementOutcome(
                    status="SAFE_FALLBACK",
                    final_answer=fallback_text,
                    violations=violations,
                    observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                )
            else:
                norm_reply = reply_without_discount
                working_reply = reply_without_discount
                repaired_claims.append({"type": "removed_unsupported_discount", "original": candidate_reply, "repaired": reply_without_discount})

    # 5. Check Product Price & Currency Contradictions / Identity Swaps / Unknown Prices
    working_reply = norm_reply

    if len(resolved_products) > 1:
        price_claims = _extract_price_claims_with_context(working_reply, all_products)
        if price_claims:
            violations.append("multi_product_price_rewritten_from_trusted_catalog")
            fallback_text = _catalog_grounded_multi_product_answer(resolved_products)
            return EnforcementOutcome(
                status="REPAIRED",
                final_answer=fallback_text,
                violations=violations,
                repaired_claims=[{"type": "multi_product_catalog_answer", "original": candidate_reply, "repaired": fallback_text}],
                observability_event={
                    "outcome": "REPAIRED",
                    "violations": violations,
                    "repaired_count": 1,
                },
            )

    for rp in resolved_products:
        p_name = rp.get("name")
        p_price = rp.get("price")
        p_curr = rp.get("currency") or "EGP"

        if not p_name:
            continue

        if p_price is None:
            claims = _extract_price_claims_with_context(working_reply, all_products)
            if claims:
                violations.append("known_product_unknown_price")
                fallback_text = f"سعر {p_name} غير متوفر بشكل موثوق حاليًا، ومش هخمنه."
                return EnforcementOutcome(
                    status="SAFE_FALLBACK",
                    final_answer=fallback_text,
                    violations=violations,
                    observability_event={"outcome": "SAFE_FALLBACK", "violations": violations},
                )

        if p_price is not None:
            p_price_float = float(p_price)
            price_claims = _extract_price_claims_with_context(working_reply, all_products)

            for claim in price_claims:
                claim_val = claim["value"]
                claim_curr = claim["currency"]
                raw_claim = claim["raw"]
                num_str = claim["num_str"]

                qty_match = re.search(r"(\d+)\s*(×|\*|من|قطعة|قطع|units)?", user_input)
                input_qty = None
                if qty_match:
                    try:
                        input_qty = int(qty_match.group(1))
                    except ValueError:
                        pass
                if not input_qty or input_qty <= 1:
                    reply_qty_match = re.search(r"(\d+)\s*(قطع|قطعة|وحدات)", working_reply)
                    if reply_qty_match:
                        try:
                            input_qty = int(reply_qty_match.group(1))
                        except ValueError:
                            pass

                expected_total = (p_price_float * input_qty) if (input_qty and input_qty > 1) else None

                # Check preceding text for total keywords
                start_idx = claim["span"][0]
                prefix_context = working_reply[max(0, start_idx - 25):start_idx].lower()
                is_total_claim = (
                    any(kw in raw_claim.lower() for kw in ["إجمالي", "اجمالي", "مجموع", "total"])
                    or any(kw in prefix_context for kw in ["إجمالي", "اجمالي", "مجموع", "total"])
                    or (expected_total is not None and abs(claim_val - expected_total) < 0.01)
                )

                if is_total_claim and expected_total is not None:
                    if abs(claim_val - expected_total) > 0.01:
                        violations.append("incorrect_quantity_total")
                        repaired_num_str = f"{expected_total:.0f}" if expected_total.is_integer() else f"{expected_total:.2f}"
                        if any(c in claim["raw"] for c in "٠١٢٣٥٦٧٨٩"):
                            repaired_num_str = repaired_num_str.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
                        working_reply = working_reply.replace(num_str, repaired_num_str)
                        repaired_claims.append({"type": "repaired_total", "from": claim_val, "to": expected_total})

                elif abs(claim_val - p_price_float) > 0.01:
                    is_swap = False
                    for other_p in all_products:
                        if other_p.name != p_name and other_p.price is not None and abs(claim_val - other_p.price) < 0.01:
                            is_swap = True
                            violations.append("cross_product_price_swap")
                            break

                    if not is_swap:
                        violations.append("wrong_known_price")

                    target_num = f"{p_price_float:.0f}" if p_price_float.is_integer() else f"{p_price_float:.2f}"
                    if any(c in raw_claim for c in "٠١٢٣٤٥٦٧٨٩"):
                        target_num = target_num.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))

                    working_reply = working_reply.replace(num_str, target_num)
                    repaired_claims.append({"type": "repaired_price", "from": claim_val, "to": p_price_float})

                if claim_curr != p_curr:
                    violations.append("wrong_currency")
                    if claim_curr == "USD" and p_curr == "EGP":
                        working_reply = re.sub(r"\bUSD\b|\bدولار\b|\$", "جنيه", working_reply, flags=re.IGNORECASE)
                        repaired_claims.append({"type": "repaired_currency", "from": claim_curr, "to": p_curr})

    # 6. Check Stock Contradictions
    for rp in resolved_products:
        stock = rp.get("stock")
        if stock is not None:
            is_out_of_stock = (str(stock).lower() in ["0", "false", "out of stock", "غير متوفر", "نفذت الكمية"])
            if is_out_of_stock and ("متوفر حالياً" in working_reply or "متوفر حاليا" in working_reply or "موجود حالياً" in working_reply):
                violations.append("wrong_stock_claim")
                working_reply = working_reply.replace("متوفر حالياً", "غير متوفر حالياً").replace("متوفر حاليا", "غير متوفر حاليا")
                repaired_claims.append({"type": "repaired_stock", "from": "in_stock", "to": "out_of_stock"})

    # 7. Check Warranty Contradictions
    for rp in resolved_products:
        warranty = rp.get("warranty")
        if warranty is not None:
            w_str = str(warranty).lower()
            if ("3" in w_str or "ثلاث" in w_str) and ("ضمان سنة" in working_reply or "ضمان 1" in working_reply):
                violations.append("wrong_warranty_claim")
                working_reply = working_reply.replace("ضمان سنة", "ضمان 3 سنوات").replace("ضمان 1 سنة", "ضمان 3 سنوات")
                repaired_claims.append({"type": "repaired_warranty", "from": "1 year", "to": "3 years"})
        else:
            if re.search(r"ضمان\s*\d+\s*(سنين|سنوات|سنة)", working_reply):
                violations.append("unknown_warranty_invented")
                working_reply = re.sub(r"ضمان\s*\d+\s*(سنين|سنوات|سنة)", "", working_reply).strip()

    if not violations:
        return EnforcementOutcome(
            status="PASS",
            final_answer=candidate_reply,
            observability_event={"outcome": "PASS", "violations": []},
        )

    if repaired_claims or working_reply != candidate_reply:
        return EnforcementOutcome(
            status="REPAIRED",
            final_answer=working_reply,
            violations=violations,
            repaired_claims=repaired_claims,
            observability_event={
                "outcome": "REPAIRED",
                "violations": violations,
                "repaired_count": len(repaired_claims),
            },
        )

    return EnforcementOutcome(
        status="PASS",
        final_answer=working_reply,
        violations=violations,
        observability_event={"outcome": "PASS", "violations": violations},
    )
