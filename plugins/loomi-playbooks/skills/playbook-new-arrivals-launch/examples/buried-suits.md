# Example: new suits buried on their category page

Illustrative only: the account, project, product, rule, segment, campaign and experiment IDs and all numbers are made up.

**Session 1 (4 November).** "Are last month's new arrivals getting seen? Boost the buried ones and email people who'd want them."

The find stage sorts 412 new products: 6 breakouts, 9 buried, 14 slow starts, 31 invisible. Four buried suits rank 40 to 90 on category page 10600. They become findings, with the slow starts and invisible products left for other skills:

```
- F1 (chosen, high): product 110071 buried; 12 days live, visits 0.3x typical, conversion 2.1x typical, rank 61. Next: discovery-product-visibility
- F2 (chosen, high): product 109874 buried; ...
- F5 (open, medium): product 108812 invisible; no views in 21 days. Next: data-feed-health
```

Outcome `boost_and_promote`. The visibility stage finds the suits match the page but have weaker performance signals than the established suits above them: `ranking_gap`. `discovery-experiment-setup` (Pattern 1) creates a disabled boost rule for the four suits, a draft experiment, and starts it, each after its own yes:

```
- C1: create rule 900201 on 2026-11-04 (in place)
- C2: create experiment 781 on 2026-11-04 (in place)
- C3: start experiment 781 on 2026-11-04 (in place, live)
```

`engagement-segment-builder` finds no segment to reuse and, after its yes, creates customer filter 5f1e09 ("viewed or bought suits in the last 90 days, with newsletter consent and an email": about 18,000 people). `engagement-email-builder` makes a "new in" draft with the four suits by ID, recorded from its plan and verify files. `campaign-qa` says GO WITH CAUTION (subject over 60 characters); the user shortens it in Engagement and schedules the send for 6 November.

```
- C6: start email campaign 6a2b91 on 2026-11-06 (in place, live)

**Next:** read-out with discovery-experiment-readout, not before 2026-11-18.
```

**Session 2 (19 November).** The read-out finds the boost won on revenue per visit for the category page. `discovery-experiment-close` ends the test keeping the boost and archives it; the user agrees to end the boost on 31 December (a separate job for `discovery-rule-cleanup`).

**Session 3 (4 December).** `change-impact-tracker` measures the kept boost at full traffic: **worked**, with its range. It measures the email launch from 6 November: orders on the four suits up, with a wide range, and the boost named as a confounder. The run is finished; the next group (new dresses) gets its own run.
