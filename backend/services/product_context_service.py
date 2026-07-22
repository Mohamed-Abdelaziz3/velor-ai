import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ProductContext:
    name: str
    aliases: List[str] = field(default_factory=list)
    price: Optional[float] = None
    currency: Optional[str] = None
    source: str = "products_data"
    confidence: float = 1.0
    missing_data: List[str] = field(default_factory=list)
    id: Optional[str] = None
    sku: Optional[str] = None
    record_type: str = "product"  # "product" | "bundle"
    category: Optional[str] = None
    description: Optional[str] = None
    stock: Optional[Any] = None
    warranty: Optional[Any] = None
    colors: List[str] = field(default_factory=list)
    quantity_discounts: List[Dict[str, Any]] = field(default_factory=list)
    components: List[Dict[str, Any]] = field(default_factory=list)
    installation: Optional[Any] = None
    installation_fee: Optional[float] = None

    def to_delivery_dict(self) -> Dict[str, Any]:
        """Compact LLM Delivery DTO excluding provenance and internal metadata."""
        d: Dict[str, Any] = {
            "name": self.name,
            "record_type": self.record_type,
        }
        if self.sku:
            d["sku"] = self.sku
        if self.price is not None:
            d["price"] = self.price
        if self.currency:
            d["currency"] = self.currency
        if self.stock is not None:
            d["stock"] = self.stock
        if self.warranty is not None:
            d["warranty"] = self.warranty
        if self.colors:
            d["colors"] = self.colors
        if self.quantity_discounts:
            d["quantity_discounts"] = self.quantity_discounts
        if self.components:
            d["components"] = self.components
        if self.installation is not None:
            d["installation"] = self.installation
        if self.installation_fee is not None:
            d["installation_fee"] = self.installation_fee
        if self.category:
            d["category"] = self.category
        if self.aliases:
            d["aliases"] = self.aliases
        if self.description:
            d["description"] = self.description
        return d

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "name": self.name,
            "aliases": list(self.aliases),
            "price": self.price,
            "currency": self.currency,
            "source": self.source,
            "confidence": self.confidence,
            "missing_data": list(self.missing_data),
        }
        if self.sku:
            res["sku"] = self.sku
        if self.record_type:
            res["record_type"] = self.record_type
        return res


_CURRENCY_ALIASES = {
    "egp": "EGP",
    "جنيه": "EGP",
    "ج.م": "EGP",
    "usd": "USD",
    "$": "USD",
    "eur": "EUR",
}


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value >= 0 else None

    text = str(value).strip()
    if not text:
        return None

    match = re.search(r"\d+(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", text)
    if not match:
        return None

    number_text = re.sub(r"[,\s]", "", match.group(0))
    try:
        parsed = float(number_text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _parse_currency(entry: Dict[str, Any], price_value: Any) -> Optional[str]:
    explicit = entry.get("currency") or entry.get("curr")
    if explicit:
        key = str(explicit).strip().casefold()
        return _CURRENCY_ALIASES.get(key, str(explicit).strip().upper() or None)

    text = str(price_value or "").casefold()
    for token, currency in _CURRENCY_ALIASES.items():
        if token.casefold() in text:
            return currency
    return None


def normalize_products_data(products_data: Optional[str]) -> List[ProductContext]:
    """
    Normalize trusted structured products_data into product context records.
    Free-form prose is intentionally ignored.
    """
    if not products_data:
        return []

    try:
        parsed = json.loads(products_data)
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    products: List[ProductContext] = []
    seen = set()
    for item in parsed:
        if isinstance(item, str):
            name = _clean_name(item)
            aliases: List[str] = []
            price_value = None
            currency = None
            sku = None
            record_type = "product"
            category = None
            description = None
            stock = None
            warranty = None
            colors: List[str] = []
            quantity_discounts: List[Dict[str, Any]] = []
            components: List[Dict[str, Any]] = []
            installation = None
            installation_fee = None
            item_id = None
        elif isinstance(item, dict):
            name = _clean_name(item.get("name") or item.get("product") or item.get("service"))
            aliases_raw = item.get("aliases") or item.get("alias") or []
            if isinstance(aliases_raw, str):
                aliases = [_clean_name(part) for part in aliases_raw.split(",")]
            elif isinstance(aliases_raw, list):
                aliases = [_clean_name(alias) for alias in aliases_raw]
            else:
                aliases = []
            aliases = [alias for alias in aliases if alias]
            price_value = item.get("price")
            currency = _parse_currency(item, price_value)

            sku = _clean_name(item.get("sku") or item.get("product_code")) or None
            record_type = str(item.get("record_type") or "product").strip()
            category = _clean_name(item.get("category")) or None
            description = str(item.get("description")).strip() if item.get("description") else None
            stock = item.get("stock")
            warranty = item.get("warranty")

            raw_colors = item.get("colors") or item.get("colours")
            if isinstance(raw_colors, list):
                colors = [_clean_name(c) for c in raw_colors if c]
            elif isinstance(raw_colors, str):
                colors = [_clean_name(c) for c in raw_colors.split(",") if c]
            else:
                colors = []

            quantity_discounts = item.get("quantity_discounts") if isinstance(item.get("quantity_discounts"), list) else []
            components = item.get("components") if isinstance(item.get("components"), list) else []
            installation = item.get("installation")
            installation_fee = _parse_price(item.get("installation_fee"))
            item_id = str(item.get("id")) if item.get("id") else None
        else:
            continue

        if not name:
            continue

        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)

        price = _parse_price(price_value)
        missing_data = []
        if price is None:
            missing_data.append("price")
        if price is not None and not currency:
            missing_data.append("currency")

        products.append(
            ProductContext(
                name=name,
                aliases=aliases,
                price=price,
                currency=currency,
                source="products_data",
                confidence=1.0,
                missing_data=missing_data,
                id=item_id,
                sku=sku,
                record_type=record_type,
                category=category,
                description=description,
                stock=stock,
                warranty=warranty,
                colors=colors,
                quantity_discounts=quantity_discounts,
                components=components,
                installation=installation,
                installation_fee=installation_fee,
            )
        )

    return products


def get_company_products(db: Optional[Session], company_id: str) -> List[ProductContext]:
    if not db:
        return []
    from database import CompanyKnowledge

    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id, CompanyKnowledge.is_deleted == False).first()
    return normalize_products_data(knowledge.products_data if knowledge else "")


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    pattern = r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _repair_mojibake(value: Any) -> str:
    """Recover a UTF-8 Arabic string that was decoded as a legacy single-byte string."""
    text = str(value or "")
    if not text or not any(marker in text for marker in ("\u00d8", "\u00d9", "\u00c3")):
        return text
    for codec in ("latin1", "cp1252"):
        try:
            decoded = text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if sum("\u0600" <= char <= "\u06ff" for char in decoded) > sum("\u0600" <= char <= "\u06ff" for char in text):
            return decoded
    return text


def _normalized_search_text(value: Any) -> str:
    text = _repair_mojibake(value)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    return (
        text.replace("\u0623", "\u0627")
        .replace("\u0625", "\u0627")
        .replace("\u0622", "\u0627")
        .replace("\u0671", "\u0627")
        .replace("\u0649", "\u064a")
        .replace("\u0629", "\u0647")
    )


_CATEGORY_ALIASES = {
    "chair": [
        "chair", "chairs", "office chair", "office chairs",
        "\u0643\u0631\u0633\u064a", "\u0643\u0631\u0633\u0649", "\u0643\u0631\u0627\u0633\u064a", "\u0643\u0631\u0627\u0633\u0649",
        "\u0643\u0631\u0633\u064a \u0645\u0643\u062a\u0628", "\u0643\u0631\u0627\u0633\u064a \u0645\u0643\u062a\u0628\u064a\u0647",
    ],
    "desk": [
        "desk", "desks", "office desk", "office desks", "standing desk", "standing desks",
        "\u0645\u0643\u062a\u0628", "\u0645\u0643\u0627\u062a\u0628", "\u0645\u0643\u062a\u0628 \u0643\u0647\u0631\u0628\u0627\u0626\u064a",
    ],
    "accessory": [
        "accessory", "accessories", "cable accessory", "cable accessories",
        "\u0627\u0643\u0633\u0633\u0648\u0627\u0631", "\u0625\u0643\u0633\u0633\u0648\u0627\u0631", "\u0627\u0643\u0633\u0633\u0648\u0627\u0631\u0627\u062a", "\u0625\u0643\u0633\u0633\u0648\u0627\u0631\u0627\u062a", "\u0645\u0644\u062d\u0642\u0627\u062a",
    ],
}


def _contains_alias(text: str, aliases: Iterable[str]) -> bool:
    for alias in aliases:
        normalized = _normalized_search_text(alias)
        if normalized and re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", text):
            return True
    return False


def _catalog_summary(products: List[ProductContext], **extra: Any) -> Dict[str, Any]:
    summary = {
        "total_records": len(products),
        "products": len([p for p in products if p.record_type == "product"]),
        "bundles": len([p for p in products if p.record_type == "bundle"]),
    }
    summary.update(extra)
    return summary


def _price_reference_matches(text: str, products: List[ProductContext]) -> List[ProductContext]:
    translated = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
    normalized = _normalized_search_text(text).translate(translated)
    numbers = [float(re.sub(r"[,\s]", "", value)) for value in re.findall(r"\d+(?:[,\s]\d{3})*(?:\.\d+)?", normalized)]
    if not numbers:
        return []
    return [product for product in products if product.price is not None and any(abs(product.price - number) < 0.001 for number in numbers)]


def match_product_mentions(text: str, products: Iterable[ProductContext]) -> List[ProductContext]:
    matches: List[ProductContext] = []
    seen = set()
    for product in products:
        candidates = [product.name, *product.aliases]
        if product.sku:
            candidates.append(product.sku)
        if any(_contains_phrase(text, candidate) for candidate in candidates):
            key = product.name.casefold()
            if key not in seen:
                seen.add(key)
                matches.append(product)
    return matches


def get_price_for_product(product: Optional[ProductContext]) -> Dict[str, Any]:
    if not product:
        return {"price": None, "currency": None, "missing_data": ["product"]}

    missing_data = []
    if product.price is None:
        missing_data.append("price")
    if product.price is not None and not product.currency:
        missing_data.append("currency")

    return {
        "price": product.price,
        "currency": product.currency,
        "missing_data": missing_data,
        "source": product.source,
    }


def estimate_deal_value(product: Optional[ProductContext], quantity: Optional[float]) -> Dict[str, Any]:
    missing_data = []
    if not product:
        missing_data.append("product")
    elif product.price is None:
        missing_data.append("price")

    if quantity is None:
        missing_data.append("quantity")
    elif quantity <= 0:
        missing_data.append("quantity")

    if product and product.price is not None and product.price >= 0 and quantity is not None and quantity > 0:
        return {
            "value": product.price * quantity,
            "currency": product.currency,
            "missing_data": ["currency"] if not product.currency else [],
            "source": product.source,
        }

    return {
        "value": None,
        "currency": product.currency if product else None,
        "missing_data": missing_data,
        "source": product.source if product else None,
    }


def resolve_runtime_product_context(user_input: str, products: List[ProductContext]) -> Dict[str, Any]:
    """
    Deterministically resolves runtime product context for a user query.
    Handles exact, normalized, SKU, multi-product, broad catalog, ambiguous, and missing products.
    """
    if not products:
        return {
            "status": "empty",
            "authoritative_source": "structured_catalog",
            "resolved_products": [],
            "candidates": [],
            "catalog_summary": {"total_records": 0, "products": 0, "bundles": 0},
        }

    text = (user_input or "").strip()
    text_clean = re.sub(r"\s+", " ", text)
    text_lower = text_clean.lower()
    text_casefold = _normalized_search_text(text_clean)

    # An explicit product name or SKU is more specific than a category word in
    # that name (for example, "Legacy Chair"). Preserve that legacy contract
    # while still resolving generic category requests before broad catalog intent.
    has_explicit_product_mention = any(
        _contains_phrase(text_clean, candidate)
        for product in products
        for candidate in (product.name, product.sku)
        if candidate
    )

    # A category is a narrower request than a catalog. Resolve it before the
    # broad-catalog branch so an office-chair query cannot list every product.
    requested_groups = [
        group
        for group, aliases in _CATEGORY_ALIASES.items()
        if _contains_alias(text_casefold, aliases)
    ]
    # "كراسي مكتب" is a chair request, not a request to merge chair and desk
    # results. A product category named "office furniture" must not turn that
    # into a catalog dump. Multiple categories remain possible only when the
    # customer explicitly joins them (for example "كراسي ومكاتب").
    if "chair" in requested_groups and "desk" in requested_groups and not re.search(r"(?:و|and)\s*(?:مكاتب|مكتب|desks?|office\s+desks?)", text_casefold):
        requested_groups = ["chair"]
    if requested_groups and not has_explicit_product_mention:
        category_matches: List[ProductContext] = []
        for product in products:
            haystack = _normalized_search_text(
                " ".join(
                    [
                        product.name or "",
                        product.category or "",
                        product.description or "",
                        " ".join(product.aliases or []),
                    ]
                )
            )
            if any(_contains_alias(haystack, _CATEGORY_ALIASES[group]) for group in requested_groups):
                category_matches.append(product)
        if category_matches:
            return {
                "status": "category_match",
                "authoritative_source": "structured_catalog",
                "resolved_products": [product.to_delivery_dict() for product in category_matches],
                "candidates": [],
                "catalog_summary": _catalog_summary(
                    products,
                    matched_records=len(category_matches),
                    requested_groups=requested_groups,
                ),
            }

    # 1. Broad Catalog Intent
    broad_patterns = [
        r"عندكم\s+إيه",
        r"عندكم\s+ايه",
        r"إيه\s+المنتجات",
        r"ايه\s+المنتجات",
        r"وريني\s+المنتجات",
        r"عرض\s+المنتجات",
        r"كل\s+المنتجات",
        r"قائمة\s+المنتجات",
        r"كتالوج",
        r"شو\s+المنتجات",
        r"ما\s+هي\s+المنتجات",
        r"المنتجات\s+المتاحة",
        r"إيه\s+المكاتب",
        r"ايه\s+المكاتب",
        r"إيه\s+الكراسي",
        r"ايه\s+الكراسي",
        r"الباندلز",
        r"البندلات",
        r"وريني\s+كل",
        r"\ball\s+products\b",
        r"\bshow\s+catalog\b",
        r"\blist\s+products\b",
        r"\bwhat\s+do\s+you\s+have\b",
        r"\bcatalog\b",
    ]
    is_broad = any(re.search(pat, text_lower, re.IGNORECASE) for pat in broad_patterns)
    if is_broad:
        return {
            "status": "broad_catalog",
            "authoritative_source": "structured_catalog",
            "resolved_products": [p.to_delivery_dict() for p in products],
            "candidates": [],
            "catalog_summary": {
                "total_records": len(products),
                "products": len([p for p in products if p.record_type == "product"]),
                "bundles": len([p for p in products if p.record_type == "bundle"]),
            },
        }

    # 2. Match products by phrase/SKU
    matched_products: List[ProductContext] = []
    matched_names = set()

    for p in products:
        candidates = [p.name, *p.aliases]
        if p.sku:
            candidates.append(p.sku)

        for cand in candidates:
            if not cand:
                continue
            cand_clean = cand.strip()
            pattern = r"(?<!\w)" + re.escape(cand_clean) + r"(?!\w)"
            if re.search(pattern, text_clean, flags=re.IGNORECASE):
                if p.name.casefold() not in matched_names:
                    matched_names.add(p.name.casefold())
                    matched_products.append(p)
                break

    # Sub-phrase matching (e.g. "Ergo One", "FocusDesk 120", "LiftDesk Electric 120")
    if not matched_products:
        for p in products:
            sub_names = [p.name]
            parts = p.name.split()
            if len(parts) > 1:
                sub_names.append(" ".join(parts[1:]))
            if len(parts) > 2 and len(parts[-1]) >= 3:
                sub_names.append(parts[-1])

            for sub in sub_names:
                if len(sub) >= 3 and sub.lower() in text_lower:
                    if p.name.casefold() not in matched_names:
                        matched_names.add(p.name.casefold())
                        matched_products.append(p)
                    break

    # A unique price mentioned in the current turn is a grounded product
    # reference, not a "not found" result. Ambiguous prices remain explicit.
    if not matched_products:
        budget_phrase_pattern = r"(?:ميزانيتي|ميزانية|budget|حدود|معايا|اقصى|أقصى|اخرى|آخري)\s*(?:حاجة|السعر)?\s*[:=]?\s*(\d{4,6})"
        if re.search(budget_phrase_pattern, text_lower):
            return {
                "status": "empty",
                "authoritative_source": "structured_catalog",
                "resolved_products": [],
                "candidates": [],
                "catalog_summary": {"total_records": len(products), "products": 0, "bundles": 0},
            }

        price_matches = _price_reference_matches(text_clean, products)
        if len(price_matches) == 1:
            return {
                "status": "resolved",
                "authoritative_source": "structured_catalog",
                "resolved_products": [price_matches[0].to_delivery_dict()],
                "candidates": [],
                "resolution_reason": "unique_price_reference",
                "catalog_summary": _catalog_summary(products),
            }
        if len(price_matches) > 1:
            return {
                "status": "ambiguous",
                "authoritative_source": "structured_catalog",
                "resolved_products": [],
                "candidates": [product.to_delivery_dict() for product in price_matches],
                "resolution_reason": "ambiguous_price_reference",
                "catalog_summary": _catalog_summary(products),
            }

    # 3. Handle Ambiguity & Result Construction
    if not matched_products:
        category_terms = {
            "chair": ["chair", "chairs", "كرسي", "كرسى", "كراسي", "كراسى", "كرسي مكتب", "كرسى مكتب"],
            "desk": ["desk", "desks", "مكتب", "مكاتب", "مكتب كهربائي", "مكاتب كهربائية"],
            "accessory": ["accessory", "accessories", "اكسسوار", "إكسسوار", "اكسسوارات", "إكسسوارات"],
        }
        requested_groups = [
            group
            for group, terms in category_terms.items()
            if any(term.casefold() in text_casefold for term in terms)
        ]
        category_matches: List[ProductContext] = []
        if requested_groups:
            for p in products:
                haystack = " ".join(
                    [
                        p.name or "",
                        p.category or "",
                        p.description or "",
                        " ".join(p.aliases or []),
                    ]
                ).casefold()
                if any(any(term.casefold() in haystack for term in category_terms[group]) for group in requested_groups):
                    category_matches.append(p)

        if category_matches:
            return {
                "status": "category_match",
                "authoritative_source": "structured_catalog",
                "resolved_products": [p.to_delivery_dict() for p in category_matches],
                "candidates": [],
                "catalog_summary": {
                    "total_records": len(products),
                    "matched_records": len(category_matches),
                    "requested_groups": requested_groups,
                },
            }

        # Check if generic term matches multiple products (e.g., "Ergo")
        ambiguous_candidates = []
        for p in products:
            if "ergo" in text_lower and "ergo" in p.name.lower():
                ambiguous_candidates.append(p)

        if len(ambiguous_candidates) > 1:
            return {
                "status": "ambiguous",
                "authoritative_source": "structured_catalog",
                "resolved_products": [],
                "candidates": [p.to_delivery_dict() for p in ambiguous_candidates],
                "catalog_summary": {"total_records": len(products)},
            }

        return {
            "status": "not_found",
            "authoritative_source": "structured_catalog",
            "resolved_products": [],
            "candidates": [],
            "catalog_summary": {
                "total_records": len(products),
                "all_product_names": [p.name for p in products],
            },
        }

    # If multiple products matched
    if len(matched_products) > 1:
        explicit_matches = []
        for p in matched_products:
            name_part = p.name.replace("Arvena ", "").strip()
            if name_part.lower() in text_lower or p.name.lower() in text_lower:
                explicit_matches.append(p)

        if len(explicit_matches) >= 2:
            return {
                "status": "resolved",
                "authoritative_source": "structured_catalog",
                "resolved_products": [p.to_delivery_dict() for p in explicit_matches],
                "candidates": [],
                "catalog_summary": {"total_records": len(products)},
            }

        if len(matched_products) > 1 and not explicit_matches:
            return {
                "status": "ambiguous",
                "authoritative_source": "structured_catalog",
                "resolved_products": [],
                "candidates": [p.to_delivery_dict() for p in matched_products],
                "catalog_summary": {"total_records": len(products)},
            }

    return {
        "status": "resolved",
        "authoritative_source": "structured_catalog",
        "resolved_products": [matched_products[0].to_delivery_dict()],
        "candidates": [],
        "catalog_summary": {"total_records": len(products)},
    }


def _context_products_from_text(text: str, products: List[ProductContext]) -> List[ProductContext]:
    normalized = _normalized_search_text(text)
    matched: List[Tuple[int, ProductContext]] = []
    for product in products:
        positions = []
        for candidate in [product.name, *product.aliases, product.sku]:
            candidate_text = _normalized_search_text(candidate)
            if candidate_text:
                position = normalized.find(candidate_text)
                if position >= 0:
                    positions.append(position)
        if positions:
            matched.append((min(positions), product))
    return [product for _, product in sorted(matched, key=lambda item: item[0])]


def _context_resolution(products: List[ProductContext], selected: List[ProductContext], reason: str) -> Dict[str, Any]:
    if len(selected) == 1:
        return {
            "status": "resolved",
            "authoritative_source": "structured_catalog",
            "resolved_products": [selected[0].to_delivery_dict()],
            "candidates": [],
            "resolution_reason": reason,
            "catalog_summary": _catalog_summary(products),
        }
    if len(selected) > 1:
        return {
            "status": "ambiguous",
            "authoritative_source": "structured_catalog",
            "resolved_products": [],
            "candidates": [product.to_delivery_dict() for product in selected],
            "resolution_reason": reason,
            "catalog_summary": _catalog_summary(products),
        }
    return {}


def resolve_conversational_product_context(
    user_input: str,
    products: List[ProductContext],
    history: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Resolve product references from the current turn and prior assistant facts.

    This stays in the catalog resolver so Web Chat, owner projections, and future
    channels share one grounded entity-resolution rule instead of separate brains.
    """
    direct = resolve_runtime_product_context(user_input, products)
    if direct.get("status") in {"resolved", "category_match", "broad_catalog"}:
        return direct

    normalized = _normalized_search_text(user_input)
    assistant_mentions: List[ProductContext] = []
    for item in reversed(list(history or [])):
        role = str(item.get("role") or item.get("sender") or "").casefold()
        content = str(item.get("content") or item.get("message") or "")
        if role not in {"assistant", "bot", "velor"} or not content:
            continue
        assistant_mentions = _context_products_from_text(content, products)
        if assistant_mentions:
            break

    first_terms = ("first", "option one", "\u0627\u0644\u0627\u0648\u0644", "\u0627\u0644\u062e\u064a\u0627\u0631 \u0627\u0644\u0627\u0648\u0644")
    second_terms = ("second", "option two", "\u0627\u0644\u062a\u0627\u0646\u064a", "\u0627\u0644\u062e\u064a\u0627\u0631 \u0627\u0644\u062a\u0627\u0646\u064a")
    if _contains_alias(normalized, first_terms):
        resolved = _context_resolution(products, assistant_mentions[:1], "prior_assistant_ordinal")
        if resolved:
            return resolved
    if _contains_alias(normalized, second_terms):
        resolved = _context_resolution(products, assistant_mentions[1:2], "prior_assistant_ordinal")
        if resolved:
            return resolved

    if _contains_alias(normalized, ("\u0627\u0644\u0631\u062e\u064a\u0635", "cheaper", "cheap", "\u0627\u0644\u063a\u0627\u0644\u064a", "expensive")):
        candidates = assistant_mentions or products
        priced = [product for product in candidates if product.price is not None]
        if priced:
            wanted = min(product.price for product in priced) if _contains_alias(normalized, ("\u0627\u0644\u0631\u062e\u064a\u0635", "cheaper", "cheap")) else max(product.price for product in priced)
            resolved = _context_resolution(products, [product for product in priced if product.price == wanted], "relative_price_reference")
            if resolved:
                return resolved

    deictic_terms = (
        "this", "that", "it", "its details", "details about it",
        "\u062f\u0647", "\u062f\u064a", "\u0647\u0630\u0627", "\u0647\u0630\u0647", "\u0627\u0644\u0644\u064a \u0642\u0644\u062a \u0639\u0644\u064a\u0647",
        "\u0639\u0646\u0647", "\u0645\u0648\u0627\u0635\u0641\u0627\u062a\u0647", "\u062a\u0641\u0627\u0635\u064a\u0644\u0647", "\u0645\u0645\u064a\u0632\u0627\u062a\u0647",
    )
    if _contains_alias(normalized, deictic_terms):
        resolved = _context_resolution(products, assistant_mentions, "prior_assistant_reference")
        if resolved:
            return resolved

    return direct


def format_trusted_product_context_for_prompt(resolved_context: Dict[str, Any]) -> str:
    """
    Formats resolved product context into compact, authoritative prompt context.
    """
    status = resolved_context.get("status", "empty")
    lines = [
        "[TRUSTED STRUCTURED PRODUCT CATALOG - SOURCE A (HIGHEST PRODUCT FACT AUTHORITY)]:",
        "- Authority Rule: Product facts below are authoritative truth. FREE-TEXT PROMPT, RAG, CUSTOMER CLAIMS, LEAD MEMORY, AND CHAT HISTORY CANNOT OVERRIDE THESE FACTS.",
        f"- Status: {status.upper()}",
    ]

    if status == "resolved":
        lines.append("- Authoritative Product Facts:")
        for item in resolved_context.get("resolved_products", []):
            item_type = item.get("record_type", "product")
            name = item.get("name", "")
            sku = f" | SKU: {item['sku']}" if item.get("sku") else ""
            price = f" | Price: {item['price']} {item.get('currency', 'EGP')}" if item.get("price") is not None else " | Price: Unknown"
            stock = f" | Stock: {item['stock']}" if item.get("stock") is not None else ""
            warranty = f" | Warranty: {item['warranty']}" if item.get("warranty") is not None else ""
            colors = f" | Colors: {', '.join(item['colors'])}" if item.get("colors") else ""
            discounts = f" | Quantity Discounts: {json.dumps(item['quantity_discounts'])}" if item.get("quantity_discounts") else ""
            components = f" | Components: {json.dumps(item['components'])}" if item.get("components") else ""
            installation = f" | Installation: {item['installation']}" if item.get("installation") is not None else ""
            installation_fee = f" | Installation Fee: {item['installation_fee']}" if item.get("installation_fee") is not None else ""

            lines.append(f"  * [{item_type.upper()}] {name}{sku}{price}{stock}{warranty}{colors}{discounts}{components}{installation}{installation_fee}")

    elif status == "broad_catalog":
        summary = resolved_context.get("catalog_summary", {})
        lines.append(f"- Discoverable Catalog Records (Total Records: {summary.get('total_records', 0)}):")
        for idx, item in enumerate(resolved_context.get("resolved_products", []), 1):
            item_type = item.get("record_type", "product")
            name = item.get("name", "")
            sku = f" (SKU: {item['sku']})" if item.get("sku") else ""
            price = f" - Price: {item['price']} {item.get('currency', 'EGP')}" if item.get("price") is not None else " - Price: Unknown"
            warranty = f" | Warranty: {item['warranty']}" if item.get("warranty") is not None else ""
            stock = f" | Stock: {item['stock']}" if item.get("stock") is not None else ""
            components = f" | Components: {json.dumps(item['components'])}" if item.get("components") else ""
            lines.append(f"  {idx}. [{item_type.upper()}] {name}{sku}{price}{warranty}{stock}{components}")

    elif status == "category_match":
        summary = resolved_context.get("catalog_summary", {})
        groups = summary.get("requested_groups", [])
        label = ", ".join(groups) if groups else "category"
        lines.append(f"- Category Match: {label} ({summary.get('matched_records', 0)} trusted records)")
        for idx, item in enumerate(resolved_context.get("resolved_products", []), 1):
            item_type = item.get("record_type", "product")
            name = item.get("name", "")
            sku = f" (SKU: {item['sku']})" if item.get("sku") else ""
            price = f" - Price: {item['price']} {item.get('currency', 'EGP')}" if item.get("price") is not None else " - Price: Unknown"
            desc = f" | {item['description']}" if item.get("description") else ""
            lines.append(f"  {idx}. [{item_type.upper()}] {name}{sku}{price}{desc}")

    elif status == "ambiguous":
        lines.append("- Candidates (Multiple matching products found. Do NOT assume a single price/product until customer clarifies):")
        for idx, item in enumerate(resolved_context.get("candidates", []), 1):
            name = item.get("name", "")
            price = f"Price: {item['price']} {item.get('currency', 'EGP')}" if item.get("price") is not None else "Price: Unknown"
            lines.append(f"  * Candidate {idx}: {name} ({price})")

    elif status == "not_found":
        lines.append("- Note: The requested product was NOT found in the authoritative catalog.")
        summary = resolved_context.get("catalog_summary", {})
        names = summary.get("all_product_names", [])
        if names:
            lines.append(f"- Available Catalog Products ({len(names)} total): {', '.join(names)}")

    elif status == "empty":
        lines.append("- Note: No structured catalog data is available for this company. Do NOT invent prices or products.")

    return "\n".join(lines)
