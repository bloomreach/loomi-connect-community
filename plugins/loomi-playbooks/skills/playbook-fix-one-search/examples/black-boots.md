# Example: fixing "black boots"

Illustrative only: the account, IDs and all numbers are made up.

**Session 1 (5 November).** "Why is 'black boots' so bad? Fix it."

The query goes into `query.txt`. The diagnosis finds poor relevance: 1,240 sessions in 30 days, conversion 1.1% against 2.9% for similar searches, bounce well above. The query finds 38 products; another wording finds 212, and no synonym links them. Each recommended fix goes in a numbered file, and the findings name only the files:

```
- F1 (chosen, high): fix file 1 synonym fix; 1240 sessions, conversion 0.011 vs 0.029, 38 vs 212 results. Next: discovery-synonym-fixer
- F2 (open, medium): fix file 2 ranking fix; rule 7012 boosts 4 products onto page one. Next: playbook-test-and-learn
- F3 (open, low): fix file 3 product data; 9 of the top 24 titles lack the colour word. Next: product-data-enhancer
```

No product was named, so the visibility stage is skipped. `discovery-change-qa` checks the one-way synonym: the target's first results are the same kind of product, no rule or test clashes: **GO** (`synonym_go`). `discovery-synonym-fixer` plans it, previews the exact change, offers staging first, creates it switched off on one yes and switches it on with another:

```
- C1: create synonym 5601 on 2026-11-05 (in place)
- C2: enable synonym 5601 on 2026-11-05 (in place, live)

**Next:** measure with change-impact-tracker, not before 2026-11-19.
```

F2 is suggested for `playbook-test-and-learn`, F3 for `product-data-enhancer`.

**Session 2 (20 November).** "Carry on with the black boots run." `change-impact-tracker` measures the query and its variants against the site-wide search trend: **worked**, conversion up with its range above zero. The run is finished.
