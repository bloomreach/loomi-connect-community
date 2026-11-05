# Example: first-time buyers who never come back

Illustrative only: the project, scenario IDs and all numbers are made up.

**Session 1 (5 November).** "Too few of our new customers buy a second time. Fix it and show me whether it worked."

The baseline stage builds the cohort matrix for May to October with definition A (first-ever purchase): 14.2% of first-time buyers have a second order by the end of month 1, 19.8% by month 3. A quarter of second orders come by day 24, the median is about day 51 (±15 days), and the pace drops after month 1. The skill's timing: nudge around day 21, a stronger offer before day 50.

The find stage maps the lifecycle flows. Two rows matter:

```
- F1 (chosen, high): flow post_purchase missing; about 3,100 first orders a month; up to 2,700.00 a month at the stated AOV and rates. Next: scenario-template-launcher
- F2 (open, low): flow replenishment missing; ... Next: scenario-template-launcher
```

`scenario-template-launcher` finds a post-purchase flow in the user's sister-brand project, previews it, and after its yes clones it as a draft:

```
- C1: create scenario 6a1f00000000000000000002 on 2026-11-05 (in place)
```

`engagement-scenario-builder` changes the first wait from 7 to 21 days and adds a condition that exits anyone with a second order (C2 and C3, update, after their own yeses). The user doesn't want an A/B test this time, so the test stage is skipped; later, `status` offers the ab-read-out stage as a skip. `scenario-qa` returns GO. The user switches the flow on in Engagement on 6 November:

```
- C4: start scenario 6a1f00000000000000000002 on 2026-11-06 (in place, live)
**Next:** performance with engagement-scenario-performance, not before 2026-12-06.
```

**Session 2 (7 December).** The ab-read-out stage is skipped (no test). `engagement-scenario-performance`: 2,950 sent, 4.4% clicked, 3.1% of recipients bought within 3 days: **measured**.

**Session 3 (5 February).** The recheck rebuilds the matrix with the same definitions. The November and December cohorts, which joined after the start, reach 16.9% and 17.4% by the end of month 1, against 13.6% to 14.8% for May to October. December's cohort includes the holiday peak, so the user waits for January's before calling it: **too early to tell**, back on 5 March. In March, January's cohort reaches 16.1%: **improved**, about two points at month 1.
