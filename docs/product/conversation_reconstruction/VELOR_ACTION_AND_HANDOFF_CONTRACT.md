# VELOR Action and Handoff Contract

Actions are typed: `REQUEST_OWNER_VERIFICATION`,
`ACCEPT_OWNER_VERIFICATION`, `CANCEL_OWNER_VERIFICATION`,
`START_HUMAN_HANDOFF`, and `PURCHASE_HANDOFF` are currently exercised by the
public engine. Offered actions are stored in state and exposed as a public-safe
button. Executed actions create a tenant-scoped lead event in the same atomic
turn as the assistant reply.

Human handoff sets `needs_human_intervention` and pauses bot replies. The UI
shows the handoff state after reload. A later customer message is persisted as
an inbound turn but does not receive a fabricated automatic reply.

Inbox handoff state and the Dashboard priority queue deliberately answer
different operational questions. A handoff is a control state; it becomes a
Dashboard `WAITING_ON_US` priority only while the latest customer turn remains
unanswered. A handoff that already has a later owner reply is visible in the
conversation history but is not an active owner-attention item.
