# VELOR Hidden Semantic Acceptance Report

## Corpus separation

- Development corpus: 300 cases, formed from 10 semantic families and 30 nearby wording/typo/register variants per family.
- Hidden acceptance corpus: 150 separate fixture-driven cases, including novel wording, mixed Arabic/English, multi-turn clarification carry, negation, correction, collisions, required slots, forbidden substitutions, outcome type, and register.

The hidden fixture is outside production code at `backend/tests/fixtures/semantic_fulfillment_hidden.json`; it is not imported by the runtime.

## Results

| Gate | Result |
| --- | --- |
| Development exact fulfillment | 300 / 300 (100%) |
| Hidden exact fulfillment | 150 / 150 (100%) |
| Mandatory V2 fixtures | 10 / 10 passed |
| Focused semantic suite | 475 passed |
| Full backend suite | 1,850 passed |
| Unrelated fact substitution | 0 observed |
| Generic discovery for a specific request | 0 observed |

The mandatory fixtures cover color, product support, recency, price-context correction, no-contact, order status, payment/order process, installments, verification acceptance, and human handoff. Assertions require the exact obligation, verifier pass, expected outcome/action, and absence of generic-product substitution rather than exact response-string matching.

## Before and after customer-visible examples

| Customer turn | Before closure | After closure |
| --- | --- | --- |
| “ألوان الكرسي إيه؟” | Broad specifications could replace the color answer. | Product clarification, then a color answer; otherwise “ألوان [المنتج] مش مسجلة…”. |
| “معايا مشكلة في الكرسي” | Could restart product discovery. | Asks what problem occurred and stays in support. |
| “اخر موديل إيه؟” | Could list availability without addressing recency. | Answers latest ordering only when documented; otherwise names missing latest-model ordering. |
| “مش غالي” | Could lose the active price context. | Acknowledges that the price is acceptable and continues only from that context. |

All corpus evaluation ran on the fallback path with the provider unavailable.
