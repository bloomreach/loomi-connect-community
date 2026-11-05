# Example: a browse abandonment flow

Illustrative only: the project, scenario IDs and all numbers are made up.

**Session 1 (5 November).** "We have no browse abandonment flow. Get one live and tell me what it makes."

The find stage maps the eight flows. Three become findings:

```
- F1 (chosen, high): flow browse_abandonment missing; about 9,000 browsers a month; up to 4,100.00 a month at the stated AOV and rates. Next: scenario-template-launcher
- F2 (open, medium): flow sunset missing; ... Next: scenario-template-launcher
- F3 (open, low): flow birthday draft; ... Next: scenario-template-launcher
```

`scenario-template-launcher` finds a browse abandonment flow in the user's sandbox project, previews the clone and lists two fixes (a consent category and a project variable). After its yes it clones it as a draft and verifies it:

```
- C1: create scenario 6a1f00000000000000000001 on 2026-11-05 (in place)
```

`engagement-scenario-builder` swaps the consent category after its own yes (C2, update). The user sets the project variable in the Engagement UI.

The user doesn't want an A/B test this time, so the test stage is skipped; later, `status` offers the ab-read-out stage as a skip. `scenario-qa` returns GO WITH CAUTION (one link not checked). The user switches the flow on in Engagement the same day, and the qa stage is recorded done with outcome `started`. The switch-on goes in the change log too, with source `engagement-ui`, so the quarter close sees it:

```
- C3: start scenario 6a1f00000000000000000001 on 2026-11-05 (in place, live)
```

```
**Next:** health with engagement-journey-health, not before 2026-11-19.
```

**Session 2 (20 November).** The flow sent 2,300 emails; one step's delivery is fine, no suppression: **healthy**. The ab-read-out stage is skipped (no test).

**Session 3 (6 December).** `engagement-scenario-performance`: 7,800 sent, 5.1% clicked, 2.9% of recipients bought within 3 days. `change-impact-tracker`: purchases by browsers up against the previous month and the site trend: **worked**, about 3,200 a month (range 1,100 to 5,300). The run is finished; F2 is next.
