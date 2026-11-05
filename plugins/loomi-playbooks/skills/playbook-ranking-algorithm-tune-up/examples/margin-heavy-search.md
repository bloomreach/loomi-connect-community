# Example: a search algorithm that leans on margin

Illustrative only: the account, algorithm, rule and experiment IDs and all numbers are made up.

**Session 1 (5 November).** "Our search algorithm leans almost entirely on margin. Fix it, but test it first."

The review stage finds the custom search algorithm 21, assigned to every search by a global algorithm rule, with one custom signal carrying most of the weight and revenue weighted at 2%. It becomes the finding:

```
- F1 (chosen, high): algorithm 21 custom signal dominates; revenue weighted near zero; ranks every search
  (about 410,000 visits in 90 days). Next: discovery-ranking-algorithm-fixer
```

The user agrees new weights. `discovery-ranking-algorithm-fixer` plans one create (a `MANUAL` copy, "Search v2") and makes it after a yes; the plan and verify files go into the change log as C1. The copy syncs for about 20 minutes, then shows `Available`.

`discovery-experiment-setup` (Pattern 3a: the global algorithm rule 900010 has no audience or schedule) creates a variant of that rule pointing at the copy, the draft experiment, enables the variant and starts the test, each after its own yes:

```
- C2: create rule 900011 on 2026-11-05 (in place)
- C3: create experiment 778 on 2026-11-05 (in place)
- C4: enable rule 900011 on 2026-11-05 (in place, live)
- C5: start experiment 778 on 2026-11-05 (in place, live)

**Next:** read-out with discovery-experiment-readout, not before 2026-11-19.
```

**Session 2 (20 November).** The read-out finds the copy's bucket won on revenue per visit. `discovery-experiment-close` ends the test keeping the variant and archives it; the confirm stage is due on 4 December.

**Session 3 (5 December).** `change-impact-tracker` measures search at full traffic: **no clear effect** against the trend, with a wide range, because every search changed at once and there's no unaffected comparison. The A/B result stands; the run is finished, and the old algorithm 21 is left for a later clean-up.
