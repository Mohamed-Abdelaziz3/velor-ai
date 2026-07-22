# VELOR Semantic Slot Contract

Slot extraction is normalized and bounded: Arabic/Egyptian and mixed-language text is tokenized, matched with bounded phrases and capability context, then resolved against the active product/category and recent conversation state. It is not an unbounded substring matcher.

## Product slots

`COLOR`, `DIMENSIONS`, `MATERIAL`, `WEIGHT_CAPACITY`, `ARMRESTS`, `LUMBAR_SUPPORT`, `HEADREST`, `ADJUSTABILITY`, `PRICE`, `AVAILABILITY`, `WARRANTY`, `MODEL_VERSION`, `RELEASE_RECENCY`, and `USAGE_SUITABILITY` are recognized with Arabic, English, and Egyptian aliases.

## Policy and operational slots

Installments, payment methods, delivery, returns, warranty, discounts, ordering, order status, support issue, human handoff, callback, owner verification, and purchase-start are typed independently of product-discovery routing.

## Resolution rules

- A supported answer uses only the resolved product/policy data.
- `PRICE` renders the documented price and currency; it never substitutes description text.
- `RELEASE_RECENCY` must use documented ordering data or explicitly say that latest-model ordering is unavailable.
- If a product is ambiguous, the response asks which product. If an identified product lacks the requested field, the response names that exact field as unavailable.
- Exact slot replies suppress duplicate product cards; optional cards are used only when they add information.

These rules are implemented in `backend/services/answer_obligation.py` and consumed by `ResponsePlan` in `backend/services/velor_chat_v2.py`.
