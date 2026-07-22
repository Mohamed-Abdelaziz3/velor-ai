# VELOR Conversation State Contract

State is a bounded JSON envelope in `Lead.pending_question`, scoped to the
tenant, visitor and `VELOR_WEB_CHAT` channel. It records schema/version,
current/recent products, comparison set, hard budget, topic, source message,
timestamps, expected answer metadata, offered action, and last executed action.

Old flat pending-question data remains readable. A state envelope from another
tenant, visitor, or channel is ignored by the capability router. The state is
written only by the atomic public-turn persistence boundary, not by the router.
