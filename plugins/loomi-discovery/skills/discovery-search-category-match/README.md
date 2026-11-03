# Discovery search and category match

For the busiest Bloomreach Discovery searches that name a category ("dresses", "mens pants", or a synonym of one), compares page one of the search with page one of the category: product overlap, brand mix, price, stock and result counts, plus the query's conversion against the category's. It recommends a redirect to the category, a ranking rule to align search with the curated category, or leaving search alone, and flags queries that match several categories.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `get_discovery_query_performance`, `get_discovery_category_performance_table`, `list_categories`, `list_synonyms_user`, `search_discovery_product_grid_insights`, `list_discovery_sites` |
| **Other requirements** | Python 3 for `scripts/category_match.py` (standard library only); the steps also work by hand |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## Example prompts

- "Do searches for our category names land on the right products?"
- "Why does searching 'dresses' show different products from the dresses page?"
- "Which category searches should we redirect to the category page?"

See [examples/category-search-check.md](examples/category-search-check.md) for illustrative output.

## Notes and limitations

- **Matching is by name, department word and synonym.** "dress" matches "dresses", "mens pants" matches `/men/pants`, and an enabled synonym can link "trouser" to "pants". Queries that match several categories are reported, not compared, because one redirect can't serve every department.
- **Page one only.** Overlap compares the first `page_size` products (in `references/rules.json`).
- **Stock** is compared only if the catalog has a stock field and it's requested in the grid `fl`.
- **Recommendations aren't made for you.** Hand each one to `discovery-change-qa` before anyone switches it on; Discovery changes are live immediately.
- Thresholds are in `references/rules.json`.
