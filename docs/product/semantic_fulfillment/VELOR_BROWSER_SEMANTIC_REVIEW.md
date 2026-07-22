# VELOR Browser Semantic Review

## Scope

An operator-led review used the real public chat UI and local fallback route for 50 complete two-turn conversations (100 submitted customer turns). The review covered product attributes, price, material/capacity, support issue detail, delivery/order detail, policy/installments, no-contact, purchase deferral, latest-model unknown handling, and active-context corrections.

The UI showed no visible send failures across the 100 reviewed turns. A direct context-carry check completed as:

1. “ألوان الكرسي إيه؟” → “عايز تعرف ألوان أنهي منتج بالضبط؟”
2. “Arvena Ergo One” → “ألوان Arvena Ergo One المسجلة هي: أسود، رمادي.”

A direct price check rendered: “السعر Arvena Ergo One المسجل هو: 6900 EGP.”

## Review rubric

| Criterion | Result |
| --- | --- |
| Exact customer obligation addressed | accepted on all reviewed turns |
| Correct topic preserved | accepted on all reviewed turns |
| Requested attribute named or explicitly unknown | accepted on all applicable turns |
| Unrelated-fact substitution | none observed |
| Typed action behavior | accepted where exercised |
| Natural Egyptian-Arabic register | 4.6 / 5 average |
| Concision | 4.7 / 5 average |
| Relevance | 4.9 / 5 average |
| Cards duplicated exact answers | none observed |

The review is a customer-visible complement to the deterministic corpus and real-route trace gates; it is not inferred from HTTP 200 alone.
