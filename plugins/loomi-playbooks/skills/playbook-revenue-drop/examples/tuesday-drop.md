# Example: a drop that started on a Tuesday

Illustrative only: the account, project, rule, campaign and scenario IDs and all numbers are made up.

**Session 1 (5 November).** "Revenue dropped 18% last week. Find out why and fix it." The run has both the Discovery account and the Engagement project.

The Discovery explainer splits the drop: conversion explains most of it, traffic is flat, and it's all in search. The daily shape is a step from Tuesday 28 October. The pixel and catalog jobs were clean. One rule changed that day:

```
- F1 (chosen, high): rule 7001 suspected cause; started 2026-10-28, 61% of the search drop, high confidence. Next: change-impact-tracker
```

`engagement-revenue-change-explainer` finds Engagement purchase revenue down 3% (buyers ×0.98, order value flat), with clean data checks: `within_normal`. The user's 18% is the Discovery dashboard's number, which the explainer reproduced, so the numbers stage is `not_needed`.

The feeds and api stages are recorded `ruled_out` (clean pixel and jobs, a step rather than an outage). The journeys and funnel stages are `ruled_out` too: the search rule explains the drop, and buyers held. `change-impact-tracker` measures rule 7001 against the site-wide search trend: **made it worse**, conversion on its queries down, with its range.

`discovery-rule-cleanup` reads rule 7001 fresh, plans a disable, checks page one with the rule switched off (GO), writes it to staging, then to production on a separate yes, and reads it back:

```
- C1: disable rule 7001 on 2026-11-05 (in place, live)

**Next:** recovery with revenue-anomaly-explainer, not before 2026-11-12.
```

**Session 2 (13 November).** The explainer compares 6 to 11 November with 28 October to 2 November: search conversion back to its level before the 28th. Outcome **recovered**, and F1 is done. `status` offers engagement-recovery as a skip (Engagement revenue didn't drop beyond normal), and the user agrees.

## Another run: Engagement only

"Email-driven revenue is down 15% month on month, but our BI says 25%." The run has only the project, so `status` offers explain, api, rollback and recovery as skips.

`engagement-revenue-change-explainer` splits October against September: buyers ×0.86, mostly fewer reactivated buyers, starting 9 October (`cause_found`). The numbers stage reconciles 15% with the BI's 25%: the BI counts orders by ship date and leaves out one store (`drop_confirmed`, use 15%). The funnel holds (`no_new_leak`). `engagement-journey-health` finds the win-back flow, scenario 412, stopped sending on 9 October after an edit (`journey_broken`). The user restarts it in the Engagement UI on 14 November; the run records it (`C1: start scenario 412 on 2026-11-14`, source `engagement-ui`) and sets engagement-recovery for 21 November with `stage --not-before`. No rule or campaign changed in the window, so the change stage is `no_recent_change` and the rollback is offered as a skip.
