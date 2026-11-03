# Discovery ranking algorithm review

Reviews the ranking algorithms in Bloomreach Discovery Ranking Studio: which search and category pages each one actually ranks, which are broken, stuck in training or syncing, unused, duplicated or stale, which rules point at a deleted algorithm or apply a search algorithm to category pages, and whose weights let one signal decide the order or ignore what shoppers do. Where traffic allows, it compares how the pages each algorithm ranks convert. You get a prioritised list: fix now, review, clean up.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `search_discovery_catalogs`, `search_ranking_algorithms`, `get_ranking_rule`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `search_discovery_product_grid_insights` |
| **Other requirements** | Python 3 for `scripts/algorithm_review.py` (standard library only) |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## Example prompts

- "Which ranking algorithms are we using, and where?"
- "Audit Ranking Studio: anything broken, stuck or unused?"
- "Is our custom margin algorithm helping or hurting?"
- "Why is this algorithm in Error?"

See [examples/algorithm-review.md](examples/algorithm-review.md) for a sample report.

## Notes and limitations

- Algorithm assignments are `ranking_algo` rules, which the ranking rule list tools leave out. The skill reads them from the product grid's debug output for the top queries and categories (20 and 15 by default), so "not seen in use" means not on those pages.
- "Converts less" compares different queries and categories, so it's a lead for an A/B test (`discovery-experiment-setup`), never proof.
- It never retrains, re-weights, renames or deletes an algorithm, and never changes a rule.
- It never repeats who last changed an algorithm or rule.
