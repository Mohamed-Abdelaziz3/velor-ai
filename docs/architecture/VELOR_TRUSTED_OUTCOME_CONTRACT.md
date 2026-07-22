# VELOR trusted outcome contract

`CONFIRMED_ORDER` and `PAID` are reserved for authenticated system-of-record
providers. Conversation text, extracted evidence, model output, lead stage,
owner actions, and suggested replies cannot establish either outcome.

The provider-neutral admission seam is
`backend/services/trusted_outcome_contract.py`. A future provider adapter must:

1. verify the provider signature or equivalent authenticity mechanism;
2. resolve the event to the current tenant and lead without trusting client
   tenant identifiers;
3. supply immutable provider event and object identifiers;
4. supply a tenant-scoped idempotency key and explicit lead/customer binding
   method;
5. supply an authoritative order ID for `CONFIRMED_ORDER` or payment ID for
   `PAID`;
6. submit timezone-aware occurred, received, and verified timestamps in order;
7. persist the adapter's verification status, SHA-256 raw-payload hash, and
   `provider_verified:<provider>` provenance;
8. submit amount/currency together when
   financial values are present;
9. use a persistence idempotency key scoped by tenant, provider, and provider
   event ID;
10. link refunds/reversals to the immutable provider event they reverse and
    keep refund amount/currency paired.

Until such an adapter and persistence layer exist, product surfaces must report
financial outcomes as `not_connected` and values as `null`. This seam is not an
integration and does not authorize displaying revenue.
