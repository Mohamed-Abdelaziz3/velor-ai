# VELOR AnswerObligation Contract

`AnswerObligation` is derived after capability routing and before response planning. It is the customer-facing completion contract for the latest turn; capability classification alone is never acceptance.

## Required fields

The typed value records `obligation_type`, requested subject/attribute/policy/action, resolved target, source message reference, required facts, forbidden substitutions, acceptable outcomes, completion criteria, confidence, and ambiguity reason. Its accepted outcomes are `DIRECT_ANSWER`, `EXPLICIT_UNKNOWN`, `CLARIFICATION`, `ACTION_EXECUTION`, and `DOMAIN_REDIRECT`.

## Supported obligation types

- Attribute and recency questions (`ATTRIBUTE_QUESTION`, `RECENCY_QUESTION`)
- Product and order support (`PRODUCT_SUPPORT_ISSUE`, `ORDER_SUPPORT_ISSUE`, `ORDER_STATUS`)
- Context updates (`CONTEXTUAL_POLARITY_UPDATE`, `REFERENCE_CORRECTION`, `NEGATIVE_CONTACT`, `PURCHASE_DEFERRAL`)
- Policy questions and explicit actions (`POLICY_QUESTION`, `ACTION_REQUEST`)
- `GENERIC`, only where no specific customer obligation exists.

## Invariants

1. The newest customer turn takes precedence over stale topic state.
2. A requested slot cannot be replaced with an available but unrelated product fact.
3. Missing product identity produces a natural product clarification; missing fact data produces an exact named unknown.
4. Context carry is bounded to the adjacent assistant clarification window; it is not speculative commercial memory.
5. An action obligation reaches the existing typed action path. It does not invent an action or commercial fact.

The implementation is in `backend/services/answer_obligation.py`; the plan consumer is `backend/services/velor_chat_v2.py`.
