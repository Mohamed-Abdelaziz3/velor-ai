# VELOR Capability Router Contract

`route_customer_capability(ctx)` returns one bounded `CapabilityDecision`:
capability, legacy-compatible plan label, policy family, offered action,
executed action, and non-sensitive routing reason.

Supported capabilities include SOCIAL, ACKNOWLEDGEMENT, CLARIFICATION,
UNRESOLVED_DIALOGUE, PRODUCT_DISCOVERY, PRODUCT_REFERENCE,
PRODUCT_SELECTION, PRODUCT_DETAILS, PRODUCT_RECOMMENDATION,
PRODUCT_COMPARISON, PRICE_QUESTION, PRICE_OBJECTION, BUDGET,
POLICY_QUESTION, UNKNOWN_COMMERCIAL_FACT, PURCHASE_ADVANCEMENT,
OWNER_VERIFICATION_REQUEST, OWNER_VERIFICATION_ACCEPTANCE,
HUMAN_HANDOFF_REQUEST, CANCELLATION, OUT_OF_DOMAIN, UNCLEAR_OR_NOISE, and
DEESCALATION.

Precedence is deliberate: cancellation and explicit human actions outrank
short acknowledgements; an offered verification action is accepted only inside
the matching tenant/visitor/channel state scope; unknown commercial fact is
reserved for explicit unverified commercial claims. Random or unrelated turns
are OUT_OF_DOMAIN, never unknown-policy prose.
