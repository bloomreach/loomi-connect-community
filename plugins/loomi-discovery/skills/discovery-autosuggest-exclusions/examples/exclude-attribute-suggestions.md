# Example: hiding "product + attribute" suggestions

Synthetic example: the account, rules, suggestions and figures are invented.

**User:** The autosuggest audit says "dress fabric" and "dress color" waste slots under "dr", and that we're wrongly hiding "Scharf", which is a brand we sell. Can you fix that? Account is `acme_store`.

**Assistant** (after reading the 3 existing rules and the "dr" and "sc" suggestions on staging, and running the plan):

## Autosuggest exclusions: acme_store (staging)

**Plan:** 3 ready changes in 3 batches · 0 blocked · 0 no change
**Warnings:** none

### Batch 1: no live impact
| # | Change | Rule | Keywords before → after | Live impact |
|---|---|---|---|---|
| 2 | Create, disabled | new: "Autosuggest clean-up" | → dress fabric, dress color | None while disabled |

**Preview**
| Prefix | Suggestions now | Expected after |
|---|---|---|
| dr | dress, black dress, dress color, dress fabric, dress length | dress, black dress, dress length |
| sc | scarf, skirt | scarf, skirt, and "scharf" may come back |

**Not written:** nothing
**Undo:** saved to `plan-staging.json`

No shopper sees a change yet. Shall I create disabled new rule 'Autosuggest clean-up'?

**User:** Yes.

**Assistant:** Created rule 4012, disabled. Next:

### Batch 2: live
| # | Change | Rule | Keywords before → after | Live impact |
|---|---|---|---|---|
| 1 | Disable | "Brands" (4003) | Scharf | "Scharf" comes back |

"Brands" holds only "Scharf", so it's disabled rather than emptied or deleted. Its undo is to enable it again.

Live at once for every shopper once it syncs (seconds to minutes). Shall I disable rule 4003 'Brands'?

**User:** Yes.

**Assistant:** Done. Last, switching on the new rule, as a batch of its own:

### Batch 3: switch on
| # | Change | Rule | Keywords | Live impact |
|---|---|---|---|---|
| 3 | Switch on | "Autosuggest clean-up" (4012) | dress fabric, dress color | Hidden for every shopper |

Live at once for every shopper once it syncs (seconds to minutes). Shall I switch on new rule 'Autosuggest clean-up'?

**User:** Yes.

**Assistant** (after reading the full rule list back and running `verify --applied 1,2,3 --created 2=4012`): All three changes are in place on staging. Two minutes later, "dr" no longer suggests "dress fabric" or "dress color", and "sc" now suggests "scharf" first. Shall I build the production plan?
