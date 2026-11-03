# Example: applying a rule audit's clean-up list

All account names, rule IDs, queries and figures are invented.

**User:** "Apply the clean-up list from the rule audit on the demo store."

**Assistant (after reading 6 rules and the experiments on staging, and building the plan):**

> I've planned 4 changes and 1 delete on **staging**. Two items are blocked.
>
> | # | Rule | Change | Before → after | Check | Undo |
> |---|---|---|---|---|---|
> | 1 | 2001 Old denim push (jeans) | disable | enabled → disabled | GO: page one keeps 22 of 24 products | `enabled: true` |
> | 2 | 2003 Boost wellies (wellies) | disable (asked to delete; it's still on) | enabled → disabled | GO | `enabled: true` |
> | 3 | 2007 Dress facets (dress) | end date | none → 31 Dec 2026 | GO | clear in the dashboard |
> | 4 | 2009 Backpack boost | queries | backpack → backpacks | GO WITH CAUTION: "backpacks" has 3× the traffic | queries: backpack |
>
> **Blocked:** 2005 is in the running test "Boots layout"; 2010 is a banner (media rules have no write tool, so here are the dashboard steps: …).
>
> The plan and undo are saved in `plan.json`. **Disable 2001 and 2003, set 2007's end date and retarget 2009 on staging?**

**User:** "Yes."

> Done. All 4 read back as planned. Next, a separate question: **permanently delete rule 2002 "Summer sale boost" (disabled, expired in August)?** This can't be undone.

**User:** "Yes, delete it."

> Deleted, and confirmed gone: the rule now reads back as not found. Do you want the same changes in **production**? I'll read the production rules and plan again first.
