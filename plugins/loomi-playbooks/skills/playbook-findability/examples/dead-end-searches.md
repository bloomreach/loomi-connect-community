# Example: dead-end searches on a fashion account

Illustrative only: the account, IDs and all numbers are made up.

**Session 1 (5 November).** "Too many searches find nothing. Fix it at the root."

The triage confirms 9 dead-end searches from the grid. Each query goes in a numbered file, and the findings name only the files:

```
- F1 (open, high): query file 1 synonym fix; 929 sessions, 0 results, variant finds 64. Next: discovery-synonym-fixer
- F2 (open, high): query file 2 synonym fix; 610 sessions, 0 results, variant finds 31. Next: discovery-synonym-fixer
- F3 (open, medium): query file 3 catalog gap; 340 sessions, no variant finds it. Next: product-data-audit
- F4 (open, low): query file 4 redirect candidate; 120 sessions. Next: discovery-redirect-fixer
```

The audit scores the 400 products in the categories those searches point at: 61 titles miss the shoppers' word for the product type. The enhancer writes suggestions for the first 20 (batch 1 of 4) as `suggestions.csv` for the feed team. The config audit finds `product_type` isn't searchable: a dashboard setting for the user, recorded as a finding.

F1 and F2 are chosen. `discovery-synonym-fixer` runs once for each, with its own plan: a one-way synonym, previewed (GO), created switched off on one yes and switched on with another. Each plan's verify file goes into the change log with `--finding`, and the new synonym's ID comes from the verify result:

```
- C1: create synonym 5501 on 2026-11-05 (in place)
- C2: enable synonym 5501 on 2026-11-05 (in place, live)
- C3: create synonym 5502 on 2026-11-05 (in place)
- C4: enable synonym 5502 on 2026-11-05 (in place, live)

**Next:** recheck with discovery-zero-results-triage, not before 2026-12-03.
```

**Session 2 (4 December).** The triage runs again from 6 November. Query files 1 and 2 now find products and sell; query file 3 still finds nothing until the feed changes land: **partly recovered**. F3 stays open for the feed team, and F4 for `discovery-redirect-fixer`.
