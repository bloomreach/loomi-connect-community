# Example: the Q4 review

Illustrative only: the account, project, IDs and all numbers are made up.

**Session 1 (5 November).** "Run the Q4 governance review for the Acme US project and the acme account, production."

Step 0 lists the runs folder: `review1.handoff.json` (Q3) has 2 open findings, so this quarter's stages check them again. The run starts as `review2.handoff.json` with the subject `2026-Q4`.

The access review covers 2 projects and 64 users; its confidential report stays with the security lead. The findings count, never name:

```
- F1 (open, high): project 5e8c leavers: remove 2 users from the leavers list; 2 leavers still have access. Owner: organisation or project administrator. Next: project-access-review
- F2 (open, medium): project 5e8c shared accounts: replace with named accounts; 1 shared login in production. Owner: organisation or project administrator. Next: project-access-review
```

`integration-inventory` finds a project variable whose value looks like a key, used by 2 live templates (F3, high), and an API trigger nothing listens to (F4, low). `data-retention-review` finds a segmentation that looks back 730 days on purchases kept 365 (F5, high: it under-counts). The organisation has no Data Hub: `no_datahub`.

**Session 2 (6 November).** "Carry on." `ad-audience-sync-health` finds one Facebook audience with no advertising consent filter (F6, high, next `engagement-segment-builder`, which the user runs separately). `discovery-catalog-config-audit` finds `name file 1` (an internal margin field) displayable: F7, high. `discovery-hidden-config-audit` finds one API parameter override past its intended end: F8, medium.

The summary groups the 8 findings by owner. The owners agree to 6 this quarter (chosen); F4 is dismissed. One of Q3's two open findings is fixed; the other is F2 again. Next review: early February.
