# Conversation Sample Review Protocol

## 1. Privacy and Security Rules
- **Explicit Permission:** Written consent must be obtained before exporting any chat data.
- **Anonymization:** A local script must be used to scrub customer names, phone numbers, addresses, and payment identifiers before the data is analyzed.
- **No Third-Party AI Training:** Anonymized data may be used for internal prompt testing via API, but MUST NOT be used to train foundational models. Ensure API providers (e.g., Groq, OpenAI) have zero-data-retention agreements for the keys used.
- **Data Isolation:** Store samples in a secure, encrypted local volume separated from production databases.
- **Retention:** All sample data must be deleted 30 days after the conclusion of the pilot analysis phase.

## 2. Annotation Framework
Every message turn in the sample data should be annotated with one or more of the following intents/states:

| Tag | Definition |
| --- | ---------- |
| `REPEATED_QUESTION` | Inquiry about a basic fact (price, size, delivery) already stated on the page. |
| `PRODUCT_DISCOVERY` | Open-ended question searching for a product (e.g., "I need a chair for my back"). |
| `PRICE_INQUIRY` | Direct question regarding the cost of an item. |
| `BUDGET_CONSTRAINT` | Explicit limitation on spending (e.g., "I only have 5000"). |
| `COMPARISON` | Asking to compare two or more specific catalog items. |
| `OBJECTION` | Expressing dissatisfaction with price, policy, or features. |
| `FOLLOW_UP_NEEDED` | Customer states they will "think about it" or "check with spouse". |
| `PURCHASE_ADVANCEMENT`| Explicit signal of readiness to buy (e.g., "I want this", "How do I pay"). |
| `OWNER_APPROVAL` | Requesting a discount or exception requiring management. |
| `ORDER_HANDOFF` | Exchange of address/payment details. |
| `COMPLAINT_RETURN` | Post-purchase issues. |
| `UNKNOWN_UNSUPPORTED`| Asking for a product the merchant doesn't sell or info not in catalog. |
| `LOST_OPPORTUNITY` | A conversation that ended abruptly with no purchase or follow-up scheduled. |
