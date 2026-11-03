# Example: applying synonym fixes

Synthetic. Every account name, ID and term is invented.

**Prompt:** "Apply the synonym fixes from the review: add tshirt, t-shirt and t shirt as one group, turn the beanie → lamp, sofa test synonym off, and delete the corset → corset one."

## Synonym changes: acme_outdoors (staging)

**Planned:** 2 · **Blocked:** 1 · **Deletes:** 0 · **Reverts:** 0

| # | Change | Before | After | Preview | Status |
|---|---|---|---|---|---|
| 1 | Create two-way | — | tshirt ↔ t-shirt ↔ t shirt | GO: all three find t-shirts (26, 65, 61 results) | Written (id 2001) |
| 2 | Disable | beanie → lamp, sofa (on) | (off) | — | Written |
| 3 | Delete | — | — | — | Blocked: synonym 3005 isn't in the user list. It's Bloomreach-generated: disable it in the Discovery dashboard |

Asked before writing: "Create the two-way group tshirt, t-shirt, t shirt and disable beanie → lamp, sofa in **staging**?" The user said yes.

**Undo:** saved in plan.json. To reverse change 1: delete synonym 2001. To reverse change 2: enable synonym 1004 (all four fields, as in the plan).
**When it takes effect:** after the next hourly sync.
**Next:** check "t-shirt" in staging after the sync, then repeat the plan for production with a fresh yes.
