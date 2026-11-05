# Example: boosting a hidden gem

Illustrative only: the account, product, rule and experiment IDs and all numbers are made up.

**Session 1 (5 November).** "Which of our products are hidden gems? Pick the best one and test boosting it."

The find stage groups 4,812 products. The top three become findings; the user picks the first:

```
- F1 (chosen, high): product 10442 hidden gem; 310 visits, conversion 6.1% vs 2.3% typical, #27 on its main query. Next: discovery-product-report
- F2 (open, medium): product 20917 fix the product page; 2,940 visits, add-to-cart 1.2% vs 5.0% typical. Next: product-data-enhancer
- F3 (open, medium): product 31008 over-exposed; 4,105 visits, conversion 0.4% vs 2.3% typical. Next: discovery-experiment-setup
```

The product report shows a complete listing, in stock in every size, and position 27 on its main query with no rule touching it: `boost_or_bury`. The listing stage is skipped. `discovery-experiment-setup` (Pattern 1) creates a disabled boost rule, a draft experiment, and starts it, each after its own yes:

```
- C1: create rule 900201 on 2026-11-05 (in place)
- C2: create experiment 781 on 2026-11-05 (in place)
- C3: start experiment 781 on 2026-11-05 (in place, live)

**Next:** read-out with discovery-experiment-readout, not before 2026-11-19.
```

**Session 2 (20 November).** The read-out finds the boost won on revenue per visit. `discovery-experiment-close` ends the test keeping the boost and archives it; its plan and verify files go into the change log, and the confirm stage is due on 4 December.

**Session 3 (5 December).** `change-impact-tracker` measures the boost at full traffic against the query as a whole: **worked**, with its range. The next finding, F2, needs its own run.
