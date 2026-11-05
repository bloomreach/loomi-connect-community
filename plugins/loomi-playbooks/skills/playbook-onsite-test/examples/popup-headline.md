# Example: a newsletter pop-up nobody tested

Illustrative only: the project, weblayer IDs and all numbers are made up.

**Session 1 (5 November).** "What should we A/B test on site? Set one up."

`onsite-experience-audit` lists 14 active weblayers. Two go on the test list:

```
- F1 (chosen, high): banner 6a2b00000000000000000001 never tested; every page, one variant at 100%, about 41,000 viewers in 30 days, 0.8% click. Next: engagement-weblayer-builder
- F2 (open, medium): banner 6a2b00000000000000000002 poor results; 68% close rate. Next: engagement-weblayer-builder
```

The user wants to test a shorter headline with the offer up front, measured on sign-ups. `engagement-weblayer-builder` rewrites the code with every piece of copy a parameter and moves the old 10-second delay into Smart triggering. The user pastes it into an inactive copy, `banner 6a2b00000000000000000003`, with two variants at 50/50: the original code and the challenger.

`engagement-weblayer-qa` returns NO-GO: the challenger's close button has no accessible label. The builder fixes it, the user pastes it, and QA returns GO. The user activates the copy and switches off the original on 6 November, planned end 4 December:

```
- C1: start banner 6a2b00000000000000000003 on 2026-11-06 (in place, live)
- C2: disable banner 6a2b00000000000000000001 on 2026-11-06 (in place, live)
**Next:** read-out with engagement-experiment-readout, not before 2026-12-04.
```

**Session 2 (5 December).** `engagement-experiment-readout`: 20,600 and 20,350 viewers, sign-up rate 1.9% against 2.6%, a lift of +37% (95% interval +18% to +58%) after four whole weeks, split on plan: **Call the winner**. The user sets the challenger to 100% in the Engagement UI (C3, update) and the finding is done. F2 is next.
