# Example: applying synonym fixes

Synthetic. Every account name, ID and term is invented.

**Prompt:** "Apply the synonym fixes from the review: add tshirt, t-shirt and t shirt as one group, turn the beanie → lamp, sofa test synonym off, and delete synonym 3005."

The plan was built with `synonym_plan.py plan --account acme_outdoors --environment staging …`.

## Synonym changes: acme_outdoors (staging)

**Ready:** 3 · **Blocked:** 1 · **No change:** 0 · **Deletes:** 0

| # | Change | Before | After | Preview | Status |
|---|---|---|---|---|---|
| 1 | Create two-way (off) | — | tshirt ↔ t-shirt ↔ t shirt | GO: all three find t-shirts (26, 65, 61 results) | Written (id 2001), in place |
| 2 | Switch on | (off) | (on) | — | Written, in place |
| 3 | Disable | beanie → lamp, sofa (on) | (off) | — | Written, in place |
| 4 | Delete | — | — | — | Blocked: synonym 3005 isn't in the user list. It's Bloomreach-generated: disable it in the Discovery dashboard |

Batches, each with its own yes:

1. "Create the two-way group tshirt, t-shirt, t shirt **switched off**, and disable beanie → lamp, sofa, in **staging**?" Yes.
2. "Switch on tshirt ↔ t-shirt ↔ t shirt (synonym 2001) in staging? It goes live after the next sync." Yes.

After each batch the read-back was checked with `synonym_plan.py verify`: every change in place.

**Undo:** saved in plan.json. To reverse changes 1 and 2: delete synonym 2001. To reverse change 3: enable synonym 1004 (all four fields, as in the plan).
**When it takes effect:** after the next hourly sync.
**Next:** check "t-shirt" in staging after the sync, then repeat the plan for production with a fresh yes.
