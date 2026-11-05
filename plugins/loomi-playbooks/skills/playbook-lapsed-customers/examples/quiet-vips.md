# Example: VIPs going quiet

Illustrative only: the project, IDs and all numbers are made up.

**Session 1 (5 November).** "How much are lapsed customers costing us? Win back the best group and tell me if it worked."

The size stage finds about 41,000 customers whose last order was 91 to 365 days ago, and no flow covering the 91-180 band:

```
- F1 (open, high): band 91-180 uncovered; about 16,000 customers, 38% with 2+ orders; 52,000.00 recoverable over 12 months. Next: engagement-segment-builder
- F2 (open, medium): band 181-365 uncovered; about 25,000 customers; 31,000.00 recoverable. Next: engagement-segment-builder
```

The refine stage tests the lapsing patterns. P3, high-value customers slowing down, is about 3,900 people inside band 91-180, 81% email-reachable, and covered by nothing. The user prefers it: F1 goes back to open and F3 is chosen.

```
- F3 (chosen, high): pattern P3 uncovered; about 3,900 customers, 81% reachable; 9,400.00 in 30 days at the stated rates. Next: engagement-segment-builder
```

`engagement-segment-builder` creates the audience after its yes (C1, `segmentation 6a6d00000000000000000009`). `scenario-template-launcher` clones a win-back flow from the sister brand's project (C2, create `scenario 6a6e0000000000000000000a`); `engagement-scenario-builder` points it at the segment and shortens the first wait (C3, update `scenario 6a6e0000000000000000000a`). As `winback-opportunity` recommends, `engagement-ab-test-setup` adds a 10% holdout before the first email, judged on purchases within 14 days and sized at six weeks; after its yes it writes the split and verifies it in place (C4, update `scenario 6a6e0000000000000000000a`). `scenario-qa`: GO, the split included. The user switches it on on 7 November, recorded as the qa stage's start date and as a change from `engagement-ui` (C5, start `scenario 6a6e0000000000000000000a`, live on 2026-11-07). The test's planned end is 19 December, so that's when to come back, though `status` would allow the readout sooner.

```
**Next:** ab-read-out with engagement-experiment-readout, not before 2026-11-21.
```

**Session 2 (19 December).** `engagement-experiment-readout`: 4.9% of the flow branch bought within 14 days against 3.6% of the holdout, lift +36% (interval +12% to +60%): **winner called** for sending. 3,500 entered, 6.8% clicked, 5.2% bought within 3 days. `change-impact-tracker`: purchases by the VIP group up against the six weeks before and against band 181-365: **worked**, about 7,200 a month (range 2,400 to 12,000).
