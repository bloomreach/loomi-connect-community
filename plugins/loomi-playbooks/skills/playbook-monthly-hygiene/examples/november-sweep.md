# Example: the November sweep

Illustrative only: the account, project, IDs and all numbers are made up.

**Session 1 (5 November).** "Run this month's hygiene sweep."

The run starts with the subject `2026-11`. The rule audit lists 23 rules; the user approves 6 for cleanup (chosen), and 2 redirect findings move to the redirect pair:

```
- F1 (chosen, high): ranking rule 2001 disable; expired 41 days ago, still on. Next: discovery-rule-cleanup
- F2 (chosen, medium): ranking rule 2014 set end date; seasonal, no end date. Next: discovery-rule-cleanup
- F7 (open, high): redirect 9003 fix URL; destination has no https. Next: discovery-redirect-fixer
```

`discovery-rule-cleanup` builds one plan, writes it to staging and then production, batch by batch, with the one delete on its own yes. Its plan and verify files go into the change log:

```
- C1: disable ranking rule 2001 on 2026-11-05 (in place, live)
- C2: update ranking rule 2014 on 2026-11-05 (in place, live)
- C6: delete ranking rule 1888 on 2026-11-05 (gone)
```

The user skips the redirect audit this month; `status` offers the redirect fix as a skip too, and F7 stays open.

**Session 2 (6 November).** "Carry on with the sweep." `engagement-asset-cleanup` finds 14 delete and archive candidates. `engagement-dependency-map` blocks 2 (an expression feeds an active scenario) and orders the other 12 in 3 steps. The user gets the order to follow in the Engagement UI; nothing is deleted by the playbook. The sweep is finished; F7 is left for December.
