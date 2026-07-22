# Phase 3 Feature Decision Log

This log governs the provisional status of existing Phase 2 features during the Phase 3 validation period. **No code demolition is approved yet.**

| Feature | Merchant Problem | Evidence | Expected Outcome | Cost / Risk | Validation Method | Provisional Decision | Reversal Condition |
|---------|------------------|----------|------------------|-------------|-------------------|----------------------|--------------------|
| **Dashboard (Analytics)** | Need to see business health | Audit shows metrics > actions | Distracts from inbox execution | High dev cost to maintain / Low risk | Do merchants ask for charts during pilot? | **Hide from pilot** | Merchants explicitly demand aggregate scores over daily actions. |
| **Ask VELOR (Copilot)** | Fast answers to business data | Audit shows it repeats UI data | Confuses merchant on where to look | High LLM cost / High hallucination risk | Is it used naturally when exposed? | **Hide from pilot** | Complex catalogs prove too hard to navigate via standard UI. |
| **Suggested Replies** | Typing takes too long | Audit shows they are often ignored | Saves typing time | High risk of sending wrong info blindly | Offer manual takeover only first | **Defer** | Typing speed becomes the #1 stated blocker for adoption. |
| **Follow-up Reminders** | Forgotten conversations | Strong | Recovers lost revenue | Low cost / Low risk | Measure recovery rate in pilot | **Expose in pilot** | Merchants ignore reminders consistently. |
| **Purchase Handoff** | Unclear checkout steps | Strong | Increases conversion | Medium cost / Low risk | Measure handoff completion | **Expose in pilot** | Merchants prefer handling payment offline entirely. |
| **Catalog Import (CSV)**| Data entry friction | Strong | Speeds up onboarding | High schema breakage risk | Test manual UI vs Import in pilot | **Test manually** | Merchants with 50+ products refuse to use UI forms. |
| **Payment Matching** | Reconciling transfers | Weak | Saves accounting time | Extreme regulatory & security risk | Ask about it in interviews | **Reject after evidence** | Becomes the absolute highest willingness-to-pay feature. |
| **Business Insights** | Strategic planning | Weak | "Nice to have" | High LLM cost | Monitor post-pilot requests | **Hide from pilot** | High retention achieved, merchants ask for expansion. |
