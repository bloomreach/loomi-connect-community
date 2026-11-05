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

`discovery-media-asset-cleanup` finds 96 assets: 2 problems on live pages (a banner image on http://, a grid placement pointing at a deleted asset) and 41 assets no rule uses, verified because every media rule was fetched in detail:

```
- F9 (open, high): asset 5521 fix image URL; image on http on a live search banner. Next: discovery-media-asset-cleanup
- F11 (open, low): asset list 1 delete in dashboard; 41 verified unused assets, oldest 2024-03-02. Next: discovery-media-asset-cleanup
```

The playbook deletes none of them: the user works through the list in the Discovery dashboard.

**Session 2 (6 November).** "Carry on with the sweep." `engagement-asset-cleanup` finds 14 delete and archive candidates. `engagement-dependency-map` blocks 2 (an expression feeds an active scenario) and orders the other 12 in 3 steps. The user gets the order to follow in the Engagement UI; nothing is deleted by the playbook. `engagement-media-cleanup` then lists 3 email images over the size limit in a live campaign, 12 images without alt text, and 58 files nothing uses (one finding, `file list 1`); templates go on its review list. The sweep is finished; F7 is left for December, and the media findings stay open until the user says the lists are done.
