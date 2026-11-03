# Ranking algorithm review: how it works and what each check means

`scripts/algorithm_review.py` applies these checks, with thresholds from `rules.json` (named in brackets). Use this file to read its output, or to apply the checks by hand.

## How an algorithm reaches a page

- Each Discovery catalog has algorithms for site search (`searchType: KEYWORD`) and for category pages (`CATEGORY`). The one with status `Default` ranks pages that nothing else assigns. Category lists may have no `Default`; then category pages use the account's built-in ranking unless a rule assigns one.
- An algorithm is assigned by a rule of type **`ranking_algo`**, whose `customizationItems` hold `{"ranking_algo": {"id": "br-…"}}`. Its query can be one search (`sitesearch`), one category (`category`), every search (`sitesearch_global`), every category page (`category_global`) or everything (`global`). It can target an audience.
- The ranking rule list tools leave `ranking_algo` rules out. The product grid's debug output lists every rule that applies to the page in `customizations.explain`, including these, and `get_ranking_rule` reads one by ID.
- Which assignment wins: one with no audience, and the most specific (`sitesearch`/`category` over `sitesearch_global`/`category_global` over `global`). Audience-targeted assignments apply only to that audience. On search pages the grid also shows `rankingAlgorithmName`; on category pages it's empty.
- `br-standard` is the `algoId` of both classic rankers, so match an assignment to the algorithm of the same page type.

## Checks

| Check | Priority | What it means |
|---|---|---|
| missing algorithm | Fix now | A rule assigns a `br-…` ID that isn't in Ranking Studio's list: deleted, or from another catalog. Those pages may fall back to the default |
| cross-type (one page) | Fix now | A rule applies a search algorithm to a category, or the other way round |
| cross-type (global) | Review | A `global` rule applies one algorithm to both search and category pages, so one kind gets an algorithm built for the other |
| error | Fix now if in use, otherwise Review | Status `Error` or a `failureMessage` |
| stuck training | Review | `In Training` for `training_stuck_days` or more since it was last changed |
| stuck sync | Review | `Syncing` for `syncing_stuck_hours` or more |
| stale | Review | A custom or manual algorithm in use, unchanged for `stale_days` or more |
| dominant signal | Review | One signal has `dominance_share` or more of the total weight |
| ignores shoppers | Review | An algorithm in use whose views, add-to-cart, conversion and revenue signals have less than `min_performance_share` of the weight |
| revenue at zero | Review | Revenue signals weighted to zero (≤ `zero_weight`) while other shopper signals count |
| custom signal | Review | A custom catalog signal (for example margin) has `custom_signal_share` or more of the weight |
| converts less | Review | The sampled pages it ranks convert below `underperform_ratio` × the others' rate (each side needs `min_visits`). A lead for an A/B test, not proof |
| not seen in use | Clean up | No sampled page uses it and it isn't the default. It may still rank pages outside the sample |
| flat signals | Clean up | Text signals whose `min` equals `max` in training but still carry weight: the field may be missing or unmapped in the catalog |
| near-duplicate | Clean up | Two algorithms of the same page type whose weights have cosine similarity ≥ `near_duplicate_similarity` |
| same name | Clean up | Two algorithms of the same page type with the same name (ignoring case and spaces) |

## Reading the weights

- Legacy details have `modelMetaData.combined`: one entry per signal with `weight`, `min`, `max` and `featureType` (`TEXT_SCORE`, `PERF`, `SEG_PERF`, `CUSTOM`). `PERF` and `SEG_PERF` are shopper-behaviour signals (views, add-to-carts, conversions, revenue, overall or by segment). `modelMetaData.text` holds the text-matching signals.
- ABR details have a `weights` list instead (`feature_key` and `display_weight`).
- The script uses each signal's share of the total absolute weight. Shares compare signals within one algorithm; they aren't comparable between legacy and ABR models.
