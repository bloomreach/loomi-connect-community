# Example: cleaning up synonyms on a swimwear and apparel account

Illustrative only: the account, synonym IDs and all numbers are made up.

**Session 1 (11 November).** "Our synonyms are a mess. Clean up the bad ones."

The review reads 214 user synonyms (191 enabled) and the newest 100 Bloomreach-generated ones, and tests what fires on 10 top queries. Existing synonyms are named by ID; the missing wording's terms go in `fix-1.txt`:

```
- F1 (chosen, high): synonym 88412 too broad: disable in dashboard; BR Generated, one-way, fires on 3 swim queries, 6400 sessions. Next: discovery-synonym-fixer
- F2 (chosen, high): fix file 1 missing wording; one-way misses the hyphenated form, 26 vs 65 results, 4100 sessions. Next: discovery-synonym-fixer
- F3 (chosen, medium): synonym 5107 bad chain: narrow targets; User Created, fires on 1 query, 900 sessions. Next: discovery-synonym-fixer
- F4 (chosen, low): synonym 5120 no-op: switch off; User Created, source equals target. Next: discovery-synonym-fixer
- F5 (chosen, low): synonym 5133 leftover test: switch off; User Created, enabled, unrelated targets. Next: discovery-synonym-fixer
- F6 (open, low): query file 1 catalog gap; synonym fires, 0 results. Next: discovery-zero-results-triage
```

The user disables synonym 88412 in the dashboard and says so; it's recorded as a `discovery-ui` change. `discovery-synonym-fixer` plans F2–F5 in one request in production. Its `discovery-change-qa` preview gives **GO** for the new two-way group and the narrowed synonym 5107. Batch 1 (create switched off, update, disables) on one yes; the switch-on on its own yes. Nobody asked to delete anything, so the leftover test synonym is switched off, not deleted:

```
- C1: disable synonym 88412 on 2026-11-11 (in place, live)
- C2: create synonym 5201 on 2026-11-11 (in place)
- C3: update synonym 5107 on 2026-11-11 (in place, live)
- C4: disable synonym 5120 on 2026-11-11 (in place)
- C5: enable synonym 5201 on 2026-11-11 (in place, live)
- C6: disable synonym 5133 on 2026-11-11 (in place)

**Next:** measure with change-impact-tracker, not before 2026-11-25.
```

**Session 2 (26 November).** "Carry on with the synonym run." `change-impact-tracker` measures the dashboard disable of synonym 88412 on the swim queries, told the expansion was removed: the synonym no longer appears in the grid's chain, and men's swim conversion **worked**, up with a range above zero against the site-wide trend. The user keeps it, and leaves F6 for a zero-results triage.
