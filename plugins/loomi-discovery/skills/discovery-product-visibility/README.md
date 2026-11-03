# Discovery product visibility

Explains why one product ranks where it does, or doesn't show at all, for a Bloomreach Discovery search query or category page. It finds the product on the live grid and classifies the cause as recall, merchandising, ranking or data, with evidence from the grid's own score breakdown and the smallest fix.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `search_discovery_product_grid_insights`, `search_discovery_catalog_products`, `list_discovery_sites`, `list_site_search_ranking_rules`, `list_category_ranking_rules`, `get_ranking_rule` |
| **Other requirements** | Python 3 for `scripts/visibility_explain.py` (standard library only) |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## Example prompts

- "Why isn't the Baroque Print Midi Dress on page one for 'dress'?"
- "Product 110743 doesn't show up when I search 'black dress'. Why?"
- "Where does SKU 12345 rank in the Outerwear category, and what's holding it back?"

## How it works

1. Fetches the grid for the query or category (up to `max_rows_per_call` rows a call, paging if needed; see `references/rules.json`).
2. If the product isn't there, checks whether it matches at all (`fq` on its ID), whether a ranking rule removes it (the same call with the rules disabled), whether it's in the search index (`search_by="product_id"`), and what the catalog says about availability, categories and text.
3. `scripts/visibility_explain.py` compares the product's relevance and performance with the products ranked above it, reads which rules boost, bury or exclude, and lists the causes.

See [examples/missing-from-page-one.md](examples/missing-from-page-one.md).

## Notes and limitations

- The grid shows a default shopper: audience-targeted rules, personalisation and A/B test buckets can rank the product differently for real shoppers.
- Facet selections a shopper makes aren't included unless you add them as filters.
- The score breakdown shows components, not the algorithm's exact weighting, so gaps show direction, not arithmetic.
- Grid responses are large (about 65 KB for 5 rows, about 300 KB for 60) because of the per-product score breakdown; the script reads saved files so the assistant doesn't have to.
