# Example: tidying filters on a fashion account

Illustrative only: the account, rule IDs and all numbers are made up.

**Session 1 (5 November).** "Our filters are a mess. Fix the worst ones."

The review looks at 8 pages (5 searches, 3 categories) covering 41,200 sessions. Changes to existing rules are named by rule ID; the new jeans rule's scope and facets go in `fix-1.txt`:

```
- F1 (chosen, high): facet rule 9101 hide and always show; all pages; internal facet with 64 values, price facet buried at position 7. Next: facet-rule-fixer
- F2 (chosen, high): fix file 1 boost; 3 bottoms searches, 9800 sessions; size shown 6th. Next: facet-rule-fixer
- F3 (dismissed, low): facet rule 9107 bury; 1 category, 610 sessions. Next: facet-rule-fixer
```

The review also lists two value merges (colour spellings) as dashboard steps. `discovery-change-qa` checks F1 and F2: no facet both shown and hidden, no running test: **GO** for both. `facet-rule-fixer` runs once per finding: an update of rule 9101 on one yes, and a new rule for the jeans searches, created switched off and switched on with its own yes:

```
- C1: update facet rule 9101 on 2026-11-05 (in place, live)
- C2: create facet rule 9120 on 2026-11-05 (in place)
- C3: enable facet rule 9120 on 2026-11-05 (in place, live)

**Next:** measure with change-impact-tracker, not before 2026-11-19.
```

**Session 2 (20 November).** "Carry on with the facet run." `change-impact-tracker` measures rule 9120 on the jeans searches, conversion as the primary metric: **no clear effect**, with a range that includes zero and the smallest effect the data could detect. The user keeps it: it was cheap and low-risk.
