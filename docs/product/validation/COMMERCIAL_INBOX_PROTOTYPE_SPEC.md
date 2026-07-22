# Commercial Inbox Prototype Specification

## 1. Goal
Validate the UI information architecture of the "Commercial Inbox" wedge with merchants before writing code. This is a static/clickable prototype (e.g., Figma or HTML mock).

## 2. Primary Screens

### Screen A: Commercial Inbox (The unified queue)
**Layout:** A single-column or split-pane list replacing the dashboard.
**Sections / Filters:**
- `Needs Action` (Urgent interventions, purchase handoffs).
- `Waiting for Customer` (Bot replied, waiting for user).
- `Follow Up` (Scheduled manual follow-ups).
- `Resolved` (Completed orders or dead leads).

**Row Data:**
- Customer Name / ID.
- Snippet of the last message.
- **Reason for attention:** (e.g., `READY TO BUY`, `UNKNOWN PRODUCT`, `BUDGET OBJECTION`).
- **Verified Context:** `[Ergo Pro] [Budget: 7000]`.
- Waiting time.
- One Primary Action Button (e.g., "Takeover", "Send Link").

### Screen B: Customer Workspace
**Layout:** Right side of the split-pane.
**Elements:**
- **Conversation Timeline:** Shows bot and human messages clearly differentiated.
- **Commercial State Panel:** 
  - Known Facts: Items requested, budget.
  - Missing Facts: Shipping address.
  - Current Stage: `Purchase Handoff`.
- **Reason for Attention:** Highlighted at the bottom of the chat.
- **Action Dock:** Input field for manual reply, "Mark as Won" button, "Schedule Follow-up" button.

### Screen C: Catalog Setup (Minimum Workflow)
**Layout:** Simple form layout.
**Elements:**
- Product Name input.
- Price input.
- Category dropdown.
- Short Description (TextArea).
- In Stock (Toggle).
- Basic Policy fields (Return days, Delivery cost).
- *No complex JSON or nested tree views.*

## 3. Prototype Testing Script
Conduct testing with 5 merchants using the prototype.

**Task 1:** "You have just logged in. Find the customer who is ready to buy but needs a payment link. What do you click?"
**Task 2:** "A customer is asking for an unavailable product. The bot has paused. Where do you go to reply and offer an alternative?"
**Task 3:** "You just received a new product shipment. Show me how you add a new chair to the system so the bot knows the price."
**Task 4:** "A customer said they will buy next week. How do you ensure you don't forget?"

*Observe success/failure without coaching.*
