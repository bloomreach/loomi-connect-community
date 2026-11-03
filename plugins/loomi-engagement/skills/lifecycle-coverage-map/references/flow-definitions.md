# Lifecycle flows: how to recognise each one

Eight flows make up a standard lifecycle programme. For each, this lists the trigger that proves it, what a working version looks like, and the signs of a weak one. `scripts/lifecycle_coverage.py` applies the trigger and keyword parts of this table, from `references/rules.json`; the "Weak" column is what you check by eye when you read the nodes.

Wait limits are in `references/rules.json`.

**Confirm from the trigger, not the name.** A scenario called "Welcome" that triggers on `session_start` is a web-layer helper, not a welcome series. Names only shortlist.

| Flow | Trigger that proves it | Working shape | Weak if |
|---|---|---|---|
| Welcome | `on-event-trigger` on `consent` (filtered to `action` = `accept`, often a `category`), or a sign-up or registration event | Consent and contact check → send within hours → 2–3 more sends over a week | First send later than `flows.welcome.max_first_wait_hours` after sign-up; a single email; the trigger listens to a category the project no longer uses |
| Browse abandonment | `on-event-trigger` on `view_item` (or `view_category`) | Wait hours → no cart add or purchase since → send with the viewed products, frequency limited | First send later than `flows.browse_abandonment.max_first_wait_hours`; no `limit` node; no purchase check |
| Cart abandonment | `on-event-trigger` on `cart_update` (`action` = `add`) or `checkout`; or a daily `repeated-trigger` on recent cart adders | Wait 1–4 hours → has the customer bought? → send → optional second send | First send later than `flows.cart_abandonment.max_first_wait_hours`; no purchase check before each send; one channel only |
| Post-purchase and review | `on-event-trigger` on `purchase` | Thank-you or cross-sell within days; review or NPS request after delivery | Only an order confirmation; no follow-up |
| Replenishment | `on-event-trigger` on `purchase` (or `purchase_item`) whose first message waits weeks, or a daily `repeated-trigger` with a "last bought N days ago" condition | Wait about one usage cycle → hasn't rebought → reminder with the product | One fixed wait for every product; no rebuy check |
| Birthday or anniversary | `on-date-attribute-trigger` on a date property (`birth_date`, `birthday`, `anniversary`), or a daily `repeated-trigger` with a "birthday is today" condition | Send on (or a week before) the date, with an offer | Uses a date property that is mostly empty (check its fill); no consent check |
| Win-back | Daily or weekly `repeated-trigger` (or `now-trigger`) on lapsing buyers: "bought before, not in the last N days" | 2–3 sends with rising incentive, by value tier | One send to everyone; no holdout; runs once and stops (`now-trigger`) |
| Sunset or re-permission | `repeated-trigger` on subscribers with no opens or clicks for months | Re-permission ask → if no response, stop emailing or withdraw consent | Missing entirely: sending to unengaged addresses hurts deliverability for every flow |

## Status

| Status | Meaning |
|---|---|
| **Live** | A scenario with `status` `active` that the trigger confirms, with a message step on a connected path |
| **Weak** | Live, but the trigger isn't connected, no message step can be reached, or the first message waits longer than the flow's limit (and anything from the Weak column you see in the nodes) |
| **Stopped** | Confirmed, but `inactive`, `paused` or `finished` |
| **Draft** | Confirmed, but never launched |
| **Missing** | No confirmed scenario |

Several scenarios can cover one flow (an email and an SMS version). The flow takes the best status among them, and the others are listed.

In testing on a demo project, every lifecycle scenario was a draft, and two templates had their trigger node left unconnected (the canvas label said "Connect the trigger to the flow before launching"). Check connections even on scenarios that look complete.

## Things that aren't scenarios

- **Standalone campaigns** (`search_email_campaigns`, `search_sms_campaigns`) can do the job of a win-back or sunset flow when they're sent regularly. Mention a recurring campaign as partial cover, but keep the flow's status as found in scenarios.
- **Transactional email** (order confirmation) is often sent by the shop platform, not Bloomreach. Don't call post-purchase missing without saying so.
- **Weblayers** can capture sign-ups, but they don't welcome anyone. Don't count them.
