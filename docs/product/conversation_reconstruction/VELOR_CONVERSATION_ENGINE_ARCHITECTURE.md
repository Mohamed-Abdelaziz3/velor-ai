# VELOR Conversation Engine Architecture

## Runtime path

`POST /api/public/chat` resolves the visitor and tenant, claims the inbound
message idempotently, invokes the V2 public engine, and commits the assistant
message, conversation state, canonical commercial lineage, action event, and
public presentation contract in `persist_v2_public_turn_atomic`.

The active V2 flow is now:

```text
Customer turn
  -> Capability Router
  -> grounded context and plan
  -> deterministic composer or verified provider writer
  -> typed conversation/action state
  -> atomic persistence + canonical commercial projection
  -> persisted public presentation envelope
```

`PUBLIC_WEB_CHAT_RESPONSE_ENGINE=v1` remains the explicit rollback only. V2 is
the default. The provider is a writer, never an authority for commercial facts.

## Removed precedence faults

The repair bypasses the old keyword-only plan selection for V2 and makes
`services/conversation_capability_router.py` the top-level capability
authority. It separates action, social, unclear, out-of-domain and policy
turns before unknown-fact handling. The remaining response writers are a
verified provider writer and deterministic fallback; both consume the same
grounded `ResponsePlan`.

## Persistence boundary

The public atomic transaction now persists `pending_question`, pause state,
typed executed actions, and the safe response envelope. Reloads and idempotent
replays retrieve the precise reply linked by `in_reply_to`, rather than the
first later assistant message.
