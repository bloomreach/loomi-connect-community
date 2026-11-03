# Example: fixing redirect audit findings

All names, IDs, URLs and figures below are invented.

**Prompt:** "The redirect audit for acme_demo flagged three things: 'returns' has no https, 'sale' is a phrase match that catches 'sale dresses', and 'return policy' duplicates 'returns'. Also add a redirect for 'track order'. Do it in staging first."

**Plan (staging), after reading the redirects, query performance and running tests:**

| # | Change | Redirect | Before | After | Live impact | Checks |
|---|---|---|---|---|---|---|
| 1 | Update URL | 9001 'returns' | `www.example-shop.test/returns` | `https://www.example-shop.test/returns` | Live once synced | — |
| 2 | Update match type | 9002 'sale' | phrase match | exact match | Live once synced | GO: 'sale dresses' (5,000 revenue) stops redirecting |
| 3 | Create (switched off) | new: 'track order', 'order status' | — | exact → `https://www.example-shop.test/orders` | None while off | GO |

Then, on its own:

| # | Change | Redirect | Before | Undo |
|---|---|---|---|---|
| 4 | Delete | 9003 'return policy' → /returns | on, audience 77 | recreate with `create_redirect` (new ID) |

> Make changes 1, 2 and 3 in staging? (yes / no)

> Delete redirect 9003 ('return policy' → /returns)? It can't be undone, only recreated. Switch it off instead? (delete / switch off / skip)

**User:** "yes. Switch 9003 off instead."

**Result:**

| # | Change | Redirect | Result | Sync | Undo |
|---|---|---|---|---|---|
| 1 | URL now https | 9001 'returns' | done | SUCCESS | `update_redirect` destination_url=`www.example-shop.test/returns` |
| 2 | Exact match | 9002 'sale' | done | SUCCESS | `update_redirect` redirect_type=`redirect_phrases` |
| 3 | Created, off | 9104 'track order' | done | SUCCESS | `delete_redirect` 9104 |
| 4 | Switched off (not deleted) | 9003 'return policy' | done | SUCCESS | `update_redirect` enabled=true |

> Switch on redirect 9104? Shoppers who search 'track order' or 'order status' will go to /orders. (yes / no)

**Not changed:** nothing. **Undo plan:** `plan-staging.json`. **Next:** check the staging site, then build the production plan.
