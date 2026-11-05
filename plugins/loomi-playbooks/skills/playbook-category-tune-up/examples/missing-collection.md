# Example: a fashion account's category pages

Illustrative only: the account, category IDs and all numbers are made up.

**Session 1 (5 November).** "Give our category pages a tune-up."

The health stage compares 140 categories with their peers. Two leaf categories convert well below their siblings, one with strong sellers buried below position 48. The dynamic review finds a "sale" collection with nothing on sale and two near-duplicate collections. The suggester finds a rising theme with no collection. The collection's name and rule go in `collection-1.txt`, and the findings name only IDs and files:

```
- F1 (open, high): category 70310 weak first screen; 3200 sessions, conversion 0.012 vs 0.026 peer median; 4 sellers below 48. Next: playbook-test-and-learn
- F2 (chosen, high): dynamic category 412 misleading name; 1800 sessions; 0 of 96 products on sale
- F3 (open, medium): dynamic category 418 overlap; 0.86 of its products also in dynamic category 409
- F4 (chosen, medium): collection file 1 new collection; 2400 sessions, up 0.41 against the baseline. Next: topic-collection-builder
```

The builder scores 180 products for the chosen topic and tests two rules: the better one returns 132 products, 0.93 on topic, catching 0.88 of the core set: **definition ready**, with the dashboard steps. F1 is suggested for `playbook-test-and-learn`.

**Session 2 (8 November).** "I fixed the sale collection and made the new one yesterday." Both changes are recorded with `--today 2026-11-07`, as made in the dashboard:

```
- C1: update dynamic category 412 on 2026-11-07 (in place, live)
- C2: create dynamic category 431 on 2026-11-07 (in place, live)

**Next:** measure with change-impact-tracker, not before 2026-11-21.
```

**Session 3 (22 November).** `change-impact-tracker` measures dynamic category 412 against its sibling categories: **worked**, bounce down and conversion up, with its range. The new collection is measured next, one change at a time.
