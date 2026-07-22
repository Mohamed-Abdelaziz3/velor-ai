# Concierge Pilot Playbook

## 1. Overview
A 14-day concierge pilot for 5 selected merchants to test the core value proposition of the VELOR Commercial Inbox. Internal VELOR operators will bridge any technical automation gaps manually to ensure the merchant experiences the exact target workflow.

## 2. Phases

### Setup (Days -3 to 0)
- **Interview & Agreement:** Complete recruitment interview and secure commitment.
- **Catalog Import:** VELOR team manually extracts the merchant's top 20 products and prices and formats them into the VELOR backend.
- **Policy Collection:** Gather standard delivery and return policies.
- **Channel Setup:** Provide the merchant with a distinct VELOR web-chat link or test WhatsApp number to route a subset of traffic.
- **Baseline Measurement:** Fill out the `pilot_baseline_form.md`.
- **Owner Training:** 15-minute walkthrough of the Commercial Inbox prototype/UI.

### Daily Operation (Days 1 to 14)
**VELOR System (Automated):**
- Receives inbound messages.
- Deterministically identifies products, prices, and constraints.
- Emits commercial lineage events.

**Internal Pilot Operator (Manual Bridge):**
- Monitors the raw event stream.
- Manually flags complex edge cases or hallucinatory AI responses before they reach the merchant (Wizard of Oz testing for safety).
- Manually populates the `daily_pilot_log.csv`.

**Merchant Role:**
- Logs into the VELOR system 2-3 times a day.
- Reviews the "Needs Action" queue.
- Performs human takeovers for `Purchase Handoff` and `Unknown` events.
- Marks conversations as Won/Lost.

### Review (Day 15)
- Conduct the `pilot_outcome_review.md` interview.
- Present the pricing continuation experiment.

## 3. Daily Merchant Output (Report)
At the end of each day, the merchant sees (or receives via email) a simplified summary:
- **Customers needing action today:** 4
- **Purchase-ready conversations captured:** 2
- **Overdue follow-ups:** 1
- **Missing catalog info identified:** 1 (e.g., "Customer asked about warranty, policy missing").
- **Completed outcomes:** 3 Orders Won.
