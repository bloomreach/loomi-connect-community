# Example: a pin rule that costs money on "gown"

Illustrative only: the account, rule and experiment IDs and all numbers are made up.

**Session 1 (5 November).** "Find out which rule on 'gown' is costing us money, and test a fix."

The find stage measures three rules. One becomes a finding:

```
- F1 (chosen, high): ranking rule 900001 hurts; pins or boosts 2 product(s); moves 5 product(s) on page one;
  estimated -470.00 (-0.0235 of the query's revenue). Next: discovery-experiment-setup
```

The user agrees to test rule 900001 without its two pins. `discovery-experiment-setup` (Pattern 2) creates the variant, the draft experiment and starts the test, each after its own yes. Each write is recorded:

```
- C1: create rule 900101 on 2026-11-05 (in place)
- C2: create experiment 777 on 2026-11-05 (in place)
- C3: enable rule 900101 on 2026-11-05 (in place, live)
- C4: start experiment 777 on 2026-11-05 (in place, live)

**Next:** read-out with discovery-experiment-readout, not before 2026-11-19.
```

**Session 2 (20 November).** "Carry on with the gown test." The read-out finds the variant won on revenue per visit. `discovery-experiment-close` ends the test keeping the variant and archives it; its plan and verify files go into the change log, and the confirm stage is due on 4 December.

**Session 3 (5 December).** `change-impact-tracker` measures the variant at full traffic against the site-wide search trend: **worked**, revenue per visit up, with its range. The run is finished.
