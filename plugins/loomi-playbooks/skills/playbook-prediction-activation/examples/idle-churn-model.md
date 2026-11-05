# Example: an idle churn model

Illustrative only: the project, IDs and all numbers are made up.

**Session 1 (5 November).** "We built a churn model months ago and I don't think anything uses it. Put it to work."

The check stage lists three predictions. Two are idle:

```
- F1 (chosen, high): prediction 6a5000000000000000000005 unused; churn model trained 9 days ago; 0 segments, 0 scenarios. Next: engagement-segment-builder
- F2 (open, low): prediction 6a5000000000000000000006 reporting only; propensity model used by 1 report. Next: engagement-segment-builder
```

`engagement-segment-builder` defines "top 20% churn score, bought in the last 180 days, with email consent", sizes it at about 14,000, and after its yes creates it (C1, create `segmentation 6a5100000000000000000007`). `scenario-template-launcher` clones a win-back flow from the sister brand's project (C2, create `scenario 6a5200000000000000000008`). `engagement-scenario-builder` points its entry condition at the new segment (C3, update `scenario 6a5200000000000000000008`). `scenario-qa`: GO. The user switches it on on 6 November, recorded as the qa stage's start date and as a change from `engagement-ui` (C4, start `scenario 6a5200000000000000000008`, live on 2026-11-06).

```
**Next:** performance with engagement-scenario-performance, not before 2026-12-06.
```

**Session 2 (8 December).** 13,100 sent across three steps, 4.0% clicked, 3.6% bought within 3 days. `change-impact-tracker`: purchases by the high-risk group up against the month before and against the rest of the base: **worked**, about 5,800 a month (range 900 to 10,700).
