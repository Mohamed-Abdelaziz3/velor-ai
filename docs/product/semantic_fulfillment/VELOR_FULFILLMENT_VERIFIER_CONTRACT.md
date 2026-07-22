# VELOR Fulfillment Verifier Contract

The deterministic verifier checks semantic completion after composition and separately from factual grounding. A reply can be factually correct yet fail this verifier if it does not answer the requested slot.

## Pass conditions

The verifier requires one of the obligation's valid outcomes:

- exact requested slot answered;
- exact requested slot named as unknown;
- required clarification asked;
- typed action executed; or
- valid domain redirect.

It rejects generic discovery substituted for a specific attribute, support, recency, or polarity request; stale-topic answers; missing requested-slot names; and duplicate card prose.

## Failure handling

Provider output gets one bounded repair attempt. Any remaining verifier failure uses the obligation-specific contextual fallback; there is no universal generic fallback.

## Audit trace and privacy

The persisted `velor_semantic_fulfillment_trace_v1` contains only capability, obligation type, requested slots, target, fact identifiers, unknown slots, planned action, and verifier outcome. Telemetry removes prompts, customer text, reply prose, visitor IDs, and tokens from acceptance evidence.

Implementation: `backend/services/fulfillment_verifier.py`, trace production in `backend/services/velor_chat_v2.py`, and sanitation in `backend/services/pilot_telemetry_service.py`.
