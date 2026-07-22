# Pilot Metrics and Decision Thresholds

## 1. Metrics Framework

### Operational
- Median first-response time (Automated vs Human baseline).
- Unhandled conversations remaining at end of day.
- Overdue follow-ups.
- Owner intervention count per day.
- Time spent checking product info (qualitative estimate).
- Order handoff completion rate.

### Commercial
- Purchase-advancement conversations (Customer explicitly states intent to buy).
- Recovered conversations (Reply after 24h silence).
- Recorded orders where VELOR attribution is defensible (Bot handled >50% of the conversation).
- Average relevant order value.
- Merchant-estimated loss prevented (*clearly marked as estimated*).

### Trust
- Unsupported-answer events (Bot speculates or hallucinates).
- Merchant corrections (Merchant overrides bot statements).
- Incorrect prices/policies quoted.
- Takeover rate (Frequency of manual overrides).
- Cases correctly marked unknown (Bot successfully defers).

### Adoption
- Days used (Logins per 14 days).
- Daily/weekly active operators.
- Actions completed through VELOR UI.
- Return usage without reminders from the VELOR team.
- Willingness to continue (Yes/No at Day 14).

### Economics
- Setup hours per merchant.
- Support hours per merchant.
- Model API cost per conversation.
- Infrastructure cost estimate.
- Gross margin estimate at target pricing.
- Acceptable support ceiling (Max hours support can spend to remain profitable).

## 2. Decision Thresholds (Based on 5 Pilots)

The strategic hypothesis (Commercial Inbox Wedge) is supported ONLY IF most of the following occur:
- **Activation:** At least 4/5 complete onboarding and route traffic.
- **Adoption:** At least 3/5 use the workflow repeatedly (daily logins).
- **Value:** At least 3/5 report a measurable operational improvement (time saved or sales recovered).
- **Commitment:** At least 2/5 agree to a paid continuation or meaningful paid pilot.
- **Safety:** No critical trust failure (zero fabricated prices leading to customer disputes).
- **Viability:** Setup/support cost is not structurally unscalable (<3 hours setup per merchant).

## 3. Pivot Criteria
- **CONTINUE:** All thresholds met. Proceed to build Phase 3C (Core Inbox).
- **REVISE:** Value proven, but adoption is low due to UI friction. Revise Inbox design.
- **CHANGE VERTICAL:** Tool works, but merchants in Vertical A refuse to pay or have unstructured catalogs. Pivot to Vertical B.
- **CHANGE WEDGE:** Merchants ignore the inbox and only want a pure Q&A widget. Re-evaluate the "Inbox" hypothesis.
- **STOP:** Massive trust failures (hallucinations), zero willingness to pay, or 0/5 merchants finish the pilot.
