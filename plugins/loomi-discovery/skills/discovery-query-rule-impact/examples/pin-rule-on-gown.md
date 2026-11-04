# Example: the rules on one search

Synthetic example: the test fixtures in `tests/fixtures/discovery/query_rule_impact/`, with page one cut to 5 products to keep it short. The products and rule IDs are made up.

**Prompt:** "What are the rules on 'gown' doing? Is any of them costing us money?"

**Calls made, one at a time:** `list_discovery_sites`; `get_discovery_query_performance` (`search="gown"`); the baseline grid; grids with 900001, 900002 and 950001 disabled one at a time, with the algorithm rule 800001 disabled, and with every rule disabled; `get_discovery_product_performance_table`; `get_discovery_product_performance` for H1 and D, saved as `rpv-1.json` and `rpv-2.json` (D: not found); one presence check for H1 with `fq='pid:"H1"'`. The query "gown" is plain letters, so it goes inline in single quotes; anything else would be written to `work/query.txt` and passed with `--query-file`.

```bash
python3 <this skill's folder>/scripts/rule_impact.py --baseline work/grid-base.json --toggled 900001=work/grid-off-900001.json --toggled 900002=work/grid-off-900002.json --toggled 950001=work/grid-off-950001.json --toggled all_algo=work/grid-off-algo.json --toggled all=work/grid-off-all.json --query-perf work/query-perf.json --query 'gown' --product-rpv work/rpv-table.json --product-rpv H1=work/rpv-1.json --product-rpv D=work/rpv-2.json --presence-check H1=work/grid-present.json --page-size 5 --out work/impact.json
```

## Rule impact: "gown" (last 30 days)

**Verdict:** Rule 900002 hides the page's best earner per visit (Beaded gown H1), and pin rule 900001 puts two weak sellers above stronger ones. Both look like they cost revenue; consider testing them, or switching them off with `discovery-rule-cleanup`.

1,000 visits · $20,000 revenue · RPV $20.00 · 5 rules on the page (3 ranking, 1 algorithm, 1 facet not measurable)

| Rule | Type | Pins / boosts | Moves on page one | Hides | Est. effect (30 days) | Verdict |
|---|---|---|---|---|---|---|
| 900002 | ranking | — | 4 | 1 (H1, above-median seller, confirmed) | −$1,045 (−5.2%) | **hides sellers** (high) |
| 900001 | ranking | X1, X2 to 1–2 | 5 | 0 | −$470 (−2.4%) | **hurts** (high) |
| All algorithm rules (800001) | algo | — | 4 | 0 | +$455 (+2.3%), covers 50% of the movement | helps |
| 950001 | ranking | — | 0 | 0 | — | no visible effect |

**Rule 900001:** pins Pinned satin gown X1 and Pinned lace gown X2 to positions 1–2 (without it they sit at 3 and 5). They earn $2.00 and $4.00 per visit, against a page median of $5.00, and push Silk evening gown A ($10.00) from 1 to 3.

**Rule 900002:** removes Beaded gown H1 from the results (`numFound` 10 with the rule, 11 without). With the rule off it ranks 3rd; its RPV is $20.00.

**Rule 950001:** no visible change, and the grid didn't echo it as disabled. Check the ID; it may target an audience.

**Not measured:** facet rule 700001. Synonyms and redirects aren't removed by the preview either.
**How the estimate works:** product RPV is across each product's whole traffic, not "gown"; the position weights are an assumption; it ignores what shoppers would have bought instead. Sequin gown D has no RPV, so the algorithm estimate covers only half the movement.
**Next:** test 900001 against no pin with `discovery-experiment-setup`, or switch off 900002 with `discovery-rule-cleanup` (after you confirm).
