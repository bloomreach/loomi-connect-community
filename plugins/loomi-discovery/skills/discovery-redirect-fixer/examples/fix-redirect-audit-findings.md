# Example: fixing redirect audit findings

All names, IDs, URLs and figures below are invented.

**Prompt:** "The redirect audit for acme_demo flagged three things: 'returns' has no https, 'sale' is a phrase match that catches 'sale dresses', and 'return policy' duplicates 'returns'. Also add a redirect for 'track order'. Do it in staging first."

**Plan (staging), after reading the redirects, query performance and running tests.** Batches: `[1, 2, 3]`, then `[4]`, then `[5]`.

| # | Change | Redirect | Before | After | Live impact | Warnings |
|---|---|---|---|---|---|---|
| 1 | update | 9001 'returns' | `www.example-shop.test/returns` | `https://www.example-shop.test/returns` | live | — |
| 2 | update | 9002 'sale' | phrase match | exact match | live | 'sale dresses' (5,000 revenue) stops redirecting |
| 3 | create (switched off) | new: 'track order', 'order status' | — | exact → `https://www.example-shop.test/orders` | none | — |

Each on its own:

| # | Change | Redirect | Before | Undo |
|---|---|---|---|---|
| 4 | enable (after change 3) | new: 'track order', 'order status' | off | `update_redirect` enabled=false |
| 5 | delete | 9003 'return policy' → /returns | on, audience 77 | recreate switched off with `create_redirect` (new ID), then switch on with its own yes |

> Make changes 1, 2 and 3 in staging? (yes / no)

**User:** "yes"

Changes 1 to 3 are written one at a time and read back. Then:

> Switch on the new redirect for 'track order' and 'order status'? Shoppers who search them will go to /orders. (yes / no)

**User:** "yes"

> Delete redirect 9003 ('return policy' → /returns)? It can't be undone, only recreated. Switch it off instead? (delete / switch off / skip)

**User:** "Switch it off instead."

Switching off isn't in the saved plan, so the assistant adds `{"action": "update", "rule_id": 9003, "enabled": false}` to the change file, builds the plan again (the new plan has one ready change, a `disable`, with the undo `update_redirect` enabled=true), shows it, and asks:

> Switch off redirect 9003 ('return policy') in staging? (yes / no)

**User:** "yes"

**Verify:** `redirect_plan.py verify` with the read-backs of changes 1 to 4 and of the new disable: all `in_place`, sync `SUCCESS`.

**Result:**

| # | Change | Redirect | Result | Sync | Undo |
|---|---|---|---|---|---|
| 1 | URL now https | 9001 'returns' | in place | SUCCESS | `update_redirect` destination_url=`www.example-shop.test/returns` |
| 2 | Exact match | 9002 'sale' | in place | SUCCESS | `update_redirect` redirect_type=`redirect_phrases` |
| 3 | Created, off | 9104 'track order' | in place | SUCCESS | `delete_redirect` 9104 |
| 4 | Switched on | 9104 'track order' | in place | SUCCESS | `update_redirect` enabled=false |
| — | Switched off (not deleted) | 9003 'return policy' | in place | SUCCESS | `update_redirect` enabled=true |

**Not changed:** the delete of 9003 (switched off instead). **Undo plans:** `plan-staging.json`, `plan-staging-2.json`. **Next:** check the staging site, then build the production plan.
