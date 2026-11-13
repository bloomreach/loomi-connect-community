# Example: why didn't this customer get the day-2 reminder?

Made-up data. IDs are placeholders.

## Prompt

> Why didn't this customer get the day-2 reminder from our "Browse abandonment" scenario? https://<instance>/p/<project-slug>/crm/customers/<customer_id>

## Output

**Verdict.** Entered on 3 Nov 2026 at 18:40 UTC from a `view_item` event, got email #4 (day-1 reminder), then went down the don't-match branch of condition #6 ("Still browsing, not bought") and left the flow, so email #8 (day-2 reminder) never fired. **Confirmed** for the route: #4 fired with status `delivered` and there's no anchor for #8. **Likely** for the cause: #6 also needs a `cart_update` in the last 2 days, and the customer had none.

**Route**

| Node | What it needs | What we found | Went to | Confidence |
|---|---|---|---|---|
| #1 Trigger: On event `view_item` | `view_item` with `category` filled | Event at 3 Nov 18:40, `category` filled | #2 | Confirmed (anchor at #4) |
| #2 Wait 1 hour | - | Arrived 18:40, left 19:40 | #3 | Confirmed |
| #3 Condition: has newsletter consent | Valid `newsletter` consent | Granted Mar 2026, not withdrawn | #4 (match) | Confirmed (anchor at #4) |
| #4 Email: day-1 reminder | `email` has a value | Anchor: `delivered` 3 Nov 19:40 | #5 | Confirmed |
| #5 Wait 23 hours | - | Arrived 3 Nov 19:40, left 4 Nov 18:40 | #6 | Confirmed |
| #6 Condition: no `purchase` since entry and `cart_update` in last 2 days | Both true at 4 Nov 18:40 | No purchase before 18:40; no `cart_update` 1-5 Nov | Don't-match (no connection) | Likely |

**Evidence**

- `view_item` 3 Nov 18:40 UTC; `campaign` #4 `delivered` 3 Nov 19:40 UTC.
- No `cart_update` events between 1 and 5 Nov.
- A `purchase` at 4 Nov 21:15 UTC came after the customer reached #6, so it played no part.

**Couldn't check**

- Nothing material: no step on this route depends on a property value from the past.

**Next step.** If the day-2 reminder should go to browsers who never added to cart, remove the `cart_update` rule from condition #6 in the Engagement UI (or ask `engagement-scenario-builder` to draft the change).
