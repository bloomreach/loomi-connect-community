# Example: ranking algorithm review

Illustrative output for a synthetic account ("Acme Outdoors"). All names, IDs and figures are made up.

**Prompt:** "Audit our Ranking Studio algorithms. Anything broken or unused?"

## Ranking algorithm review: Acme Outdoors (2026-11-03; sample: top 20 queries, 15 categories, last 30 days)

**Summary:** 11 algorithms (7 search, 4 category). Defaults: search "Classic search ranking", category built-in (none marked Default; a category-wide rule applies "Classic category ranking"). 2 to fix now, 9 to review, 6 to clean up.

### Where each algorithm is used

| Algorithm | Type | Status | Pages it ranks (sample) | Visits | Revenue | Last changed |
|---|---|---|---|---|---|---|
| Classic search ranking (br-standard) | Classic | Default | 14 queries (no rule) | 31,200 | $412,000 | 2024-08-25 |
| Text relevance (br-text) | Manual | Available | "dress" (query rule), category 200 (category rule) | 7,000 | $60,000 | 2025-06-21 |
| Margin (br-margin) | ML custom | Available | "shirt" and 4 more (global rule); "dress" for VIP shoppers only | 4,000 | $9,000 | 2026-10-04 |
| Classic category ranking (br-standard) | ML global | Available | 13 categories (category-wide rule) | 41,000 | $388,000 | 2024-08-25 |

### Fix now

| Algorithm | Issue | Evidence | Action |
|---|---|---|---|
| br-deleted | Missing algorithm | Rule 503 on "ghost" applies an algorithm that isn't in Ranking Studio | Point the rule at an existing algorithm or remove it; preview with discovery-change-qa |
| Text relevance (br-text, search) | Search algorithm on a category page | Rule 951 applies it to category 200 | Apply a category algorithm instead; preview with discovery-change-qa |

### Review

| Algorithm | Issue | Evidence | Action |
|---|---|---|---|
| Margin (br-margin) | Global rule on search and category pages | Rule 900 is `global` | Split into a search-wide and a category-wide rule |
| Margin (br-margin) | Custom signal drives the order; converts less | margin has 50% of the weight; its pages convert at 1.0% vs 4.0% | A/B test it against the default (discovery-experiment-setup) |
| Text relevance (br-text) | Stale; one signal dominates | Unchanged for 1.4 years; text score has 52% of the weight | Check the weights, or A/B test against the default |
| New ABR (br-train) | Stuck in training | In Training for 10 days | Check the training in Ranking Studio |
| Broken model (br-err) | Error | "Training data missing"; not seen in use | Repair or remove |

### Clean up

| Algorithm | Issue | Evidence | Action |
|---|---|---|---|
| Text Relevance (br-copy) | Near-duplicate and same name as br-text | Weights 100% similar | Keep one, rename or remove the other |
| Category optimised (br-cat) | Not seen in use; flat signals | Not on the sampled pages; colour and gender signals never varied | Check its rules before removing; check the feed (product-data-audit) |

**Not checked:** category 400 (no assignment and no category default); weights of "Classic category ranking" (no detail fetched).
**Next steps:** A/B test Margin and Text relevance against the default with discovery-experiment-setup; preview the two fixes with discovery-change-qa before making them in Ranking Studio.
