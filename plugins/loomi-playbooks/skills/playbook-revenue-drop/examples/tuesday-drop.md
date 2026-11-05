# Example: a drop that started on a Tuesday

Illustrative only: the account, project and rule IDs and all numbers are made up.

**Session 1 (5 November).** "Revenue dropped 18% last week. Find out why and fix it."

The explainer splits the drop: conversion explains most of it, traffic is flat, and it's all in search. The daily shape is a step from Tuesday 28 October. The pixel and catalog jobs were clean. One rule changed that day:

```
- F1 (chosen, high): rule 7001 suspected cause; started 2026-10-28, 61% of the search drop, high confidence. Next: change-impact-tracker
```

The feeds and api stages are recorded `ruled_out` (clean pixel and jobs, a step rather than an outage). The journeys stage is `ruled_out` too: the search rule explains the drop. `change-impact-tracker` measures rule 7001 against the site-wide search trend: **made it worse**, conversion on its queries down, with its range.

`discovery-rule-cleanup` reads rule 7001 fresh, plans a disable, checks page one with the rule switched off (GO), writes it to staging, then to production on a separate yes, and reads it back:

```
- C1: disable rule 7001 on 2026-11-05 (in place, live)

**Next:** recovery with revenue-anomaly-explainer, not before 2026-11-12.
```

**Session 2 (13 November).** The explainer compares 6 to 11 November with 28 October to 2 November: search conversion back to its level before the 28th. Outcome **recovered**, and F1 is done.
