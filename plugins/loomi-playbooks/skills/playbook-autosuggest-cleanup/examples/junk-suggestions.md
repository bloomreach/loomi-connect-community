# Example: cleaning up autosuggest on a fashion account

Illustrative only: the account, rule IDs and all numbers are made up.

**Session 1 (5 November).** "Autosuggest offers junk. Clean it up."

The audit types 14 prefixes covering the top 20 queries: 3 suggestions lead to dead ends or weak results, 2 are "product + attribute" suggestions, and one existing rule hides a brand the catalog carries. Each keyword goes in a numbered file, and the findings name only the files:

```
- F1 (chosen, high): keyword file 1 exclude; position 2 for a 2-letter prefix; 410 sessions, 0 orders. Next: discovery-autosuggest-exclusions
- F2 (chosen, high): keyword file 2 exclude; position 4; 220 sessions, conversion 0.004 vs 0.027. Next: discovery-autosuggest-exclusions
- F3 (chosen, medium): keyword file 3 unexclude; rule 104 hides it; 190 sessions a month typed in full. Next: discovery-autosuggest-exclusions
- F4 (open, medium): keyword file 4 synonym fix; suggested wording finds 26 products, another finds 65. Next: discovery-synonym-fixer
```

`discovery-autosuggest-exclusions` plans all three in one request: a new rule for F1 and F2, created disabled, and an update of rule 104 without F3's keyword. It runs in staging first, then production with a new plan and a new yes. The production plan and verify files go into the change log. The skill's verify report shows all three in place, and so does the change log:

```
- C1: update rule 104 on 2026-11-05 (in place, live)
- C2: create rule 131 on 2026-11-05 (in place)
- C3: enable rule 131 on 2026-11-05 (in place, live)

**Next:** recheck with autosuggest-audit, not before 2026-12-03.
```

F4 is suggested for `discovery-synonym-fixer`.

**Session 2 (4 December).** The audit runs again on the same prefixes, from 6 November. Keyword files 1 and 2 no longer show, and the brand suggestion is back; one new near-duplicate appears and becomes F5: **partly cleaned**.
