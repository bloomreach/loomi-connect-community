# Triage playbook

This file matches the evidence for each dead-end query to a class and a fix. Pick the smallest fix that explains the evidence.

## Evidence needed for each class

| Class | Evidence required before you call it | Fix | Effort / risk |
|---|---|---|---|
| **Synonym / spelling fix** | A variant wording returns **relevant** products (judge the titles, not just `numFound`) | One-way synonym from the shopper's word to the catalog's word (e.g. capris → cropped trousers). Use two-way only when both words describe the same products | Low / low |
| **Spelling fix** | The query is a misspelling, `did_you_mean` is empty or wrong, and the corrected word returns relevant products | One-way synonym from the misspelling to the correct word | Low / low |
| **Catalog gap** | Nothing relevant in **any** variant, in **both** `search_mode="hybrid"` and `"standard"` | Redirect to the nearest category or a content page, or show a banner; report the gap, its sessions and its growth to merchandising | Low / low (redirect); assortment decision for the gap |
| **Redirect candidate** | The query is about a page or service (returns, delivery, gift card, store, app), or it's a catalog gap with a clear nearest category | Redirect | Low / low |
| **Noise** | Below the sessions threshold, gibberish, a one-off long sentence, or bot-like (identical sessions every day, 100% bounce, no product views, across many unrelated terms) | None. Mention it, then move on | — |

## Cross-cutting causes to check

| Evidence | Cause | Fix |
|---|---|---|
| A rule in `customizations.explain` targets this exact query, with `ruleType: "algo"`, `query_relaxation: "off"` and `query_spellcorrect: "off"`, while the global rule allows them | A query-level search-settings rule makes the query stricter than the rest of the site | Review the rule. Disable it, or switch relaxation back on, then preview in the product grid. If many dead-end queries each have one, treat them as one pattern |
| A user synonym has the same source and target (e.g. "corset → corset") | A no-op synonym, often a failed attempt at a fix | Replace it with a real mapping to the catalog's wording, or delete it if the query is a catalog gap |
| A Bloomreach-generated synonym expands the query to unrelated products (e.g. "straw" → "coffee stirrers") | Bad automatic synonym | Recommend the `discovery-synonym-review` skill |
| Results are relevant, `numFound` > 0, but analytics shows 0 product views | The front end isn't showing these results (front-end redirect, override, or broken tracking) | Not a search-config fix. Ask the web team to check the search results page for the query |
| Hybrid mode returns many results, but the titles are off-topic | Semantic matching fills an empty result set with loosely related products | Treat as a catalog gap. Don't count the results as a match |
| Spelling correction rewrites the query into something unrelated (in testing, "swim trunks" became "slim trends") | Spelling correction picks the nearest catalog words | A synonym or redirect for the exact query stops the rewrite |

## Sessions at stake

Use: `sessions × typical revenue per search session` (the median of revenue ÷ sessions over the 20 busiest top searches; `scripts/triage_candidates.py` prints it as `revenue_at_stake`).

- It's an estimate for the period, not a forecast. It assumes the query would earn like a typical top query once fixed.
- For a catalog gap, a redirect recovers only part of it. Say "partly recoverable".
- Show the period-on-period change in sessions too. A dead end that is growing quickly matters more than its current size suggests.

## Ordering

1. Patterns that fix many queries at once (blocking rules, a family of no-op synonyms).
2. Synonym and spelling fixes, by sessions.
3. Redirect candidates, by sessions.
4. Catalog gaps, by sessions and growth.
5. Noise: count only.
