# Example: redirecting "dresses" to its category

Illustrative only: the account, redirect IDs and all numbers are made up.

**Session 1 (5 November).** "Do our category-name searches land as well as the category pages? Fix the worst one."

The match stage checks 14 category-name searches: 2 to redirect, 1 to align, 3 ambiguous (never redirected). The query text goes into `query-1.txt`, `query-2.txt` and `query-3.txt`, and the findings name only the files:

```
- F1 (chosen, high): query file 1 redirect; overlap 0.12; category converts 0.31 better; 4210 sessions. Next: discovery-redirect-fixer
- F2 (open, medium): query file 2 redirect; overlap 0.20; category converts 0.18 better; 1890 sessions. Next: discovery-redirect-fixer
- F3 (open, low): query file 3 align ranking; overlap 0.71; category converts 0.22 better; 960 sessions. Next: playbook-test-and-learn
```

The user picks F1 and confirms the category URL. `discovery-redirect-fixer` plans an exact-match redirect, previews it, creates it switched off on one yes and switches it on with another. Its plan and verify files go into the change log, with the new redirect's ID from the verify result:

```
- C1: create redirect 9101 on 2026-11-05 (in place)
- C2: enable redirect 9101 on 2026-11-05 (in place, live)

**Next:** measure with change-impact-tracker, not before 2026-11-19.
```

F3 is suggested for `playbook-test-and-learn`; F2 waits for a new run.

**Session 2 (20 November).** "Carry on with the search-vs-category run." `change-impact-tracker` measures the dresses category page against the category trend: **worked**, visits to the category up with conversion steady, with its range. The run is finished.
