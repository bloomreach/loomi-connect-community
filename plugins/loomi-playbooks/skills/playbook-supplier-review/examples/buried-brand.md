# Example: a brand buried on "mens belt"

Illustrative only: the account, brand, rule and experiment IDs and all numbers are made up.

**Session 1 (5 November).** "We meet the supplier next month. How is the brand doing, and would a boost pay?"

The brand name goes in `brand.txt` for the run's subject. The review scores it: 4.2% of revenue from 2.8% of views (exposure index 1.5), converting above average. Its ranking check finds one query worth a test:

```
- F1 (chosen, high): query file 1 buried; 25 matching products, 0 in first 24, median position 103;
  14800 sessions in 90 days. Next: discovery-experiment-setup
```

The query has no enabled rule, so `discovery-experiment-setup` uses Pattern 1: a boost at strength 40, created disabled, a draft experiment, then the start, each after its own yes:

```
- C1: create rule 900201 on 2026-11-05 (in place)
- C2: create experiment 778 on 2026-11-05 (in place)
- C3: start experiment 778 on 2026-11-05 (in place, live)

**Next:** read-out with discovery-experiment-readout, not before 2026-11-19.
```

**Session 2 (20 November).** The read-out finds the boost won on revenue per visit. `discovery-experiment-close` ends the test keeping it and archives it; its plan and verify files go into the change log.

**Session 3 (21 November).** The review runs again for the brand, and its talking points gain the result: "A two-week test on 'mens belt' moved your belts onto page one and raised revenue per visit for that search, at the confidence and range shown; the boost is now live." The run is finished.
