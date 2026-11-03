# Catalog parity check

Compares the Bloomreach Discovery catalog (search and category pages) with the Bloomreach Engagement catalog that feeds recommendations and emails. It samples the products that earn the money first (top sellers and page one of the top searches), then a random sample from each catalog, and finds:

- products **in one catalog but not the other**, with the ID mapping it used stated;
- products whose **price, sale price, stock, URL, image or title** disagree.

It reports each mismatch rate on a random sample of the Discovery catalog with its size and a 95% interval (the Engagement side is reported separately, because it can only be reached in its first 1,000 items), and lists the products to fix first, ranked by revenue at stake (for example a recommendation email linking to a product that is out of stock on the site). It never changes anything.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `search_discovery_catalogs`, `search_discovery_catalog_products`, `get_discovery_product_performance_table`, `get_discovery_query_performance`, `search_discovery_product_grid_insights`, `list_cloud_organizations`, `list_projects`, `search_catalogs`, `search_catalog_items`, `get_catalog_item` (via `search_tools` and `call_tool`), `get_mapping` |
| **Other requirements** | Python 3 for `scripts/catalog_parity.py` (optional; standard library only) |
| **Tested with** | Claude Code (read-only calls in November 2026 to check tool names and response shapes: Discovery catalog records and not-found lookups on a Bloomreach demo account; Engagement catalog lists, item pages, item lookups by ID and not-found lookups on a demo project. The demo's two catalogs hold different products, so no end-to-end parity run yet. The script is tested on synthetic fixtures) |
| **Maintainer** | Bloomreach |

## Example prompts

- "Do our Discovery and Engagement catalogs match?"
- "Our recommendation emails keep showing out-of-stock products. Is the Engagement catalog out of date?"
- "Check prices and stock between search and recommendations for our top sellers."

See [examples/example-parity-report.md](examples/example-parity-report.md) for an illustrative report.

## Scripts

- `scripts/catalog_parity.py`: joins the saved Discovery and Engagement records on the shared ID, compares the six fields, and prints the mismatch rates (Discovery random sample, with Wilson intervals that assume independent draws), the Engagement-side and priority-sample rates and the products with findings, ranked by priority and revenue at stake. Thresholds, field names and stock words are in `references/rules.json`. Standard library only; no network access.

## Notes and limitations

- **One product at a time.** Neither catalog tool looks up a batch of IDs, so a full run takes about 150–250 calls. The skill says so before it starts and offers a smaller sample.
- **Engagement can only be sampled in its first 1,000 items** (`search_catalog_items` caps `skip + count` at 1,000). Lookups by ID reach every item.
- **Data Hub-managed Discovery catalogs** aren't supported yet: `search_discovery_catalog_products` returns an error for them.
- **Stock depends on the catalog's fields.** The script reads the first stock field present (`availability`, `stock_level`, `active` and others in `rules.json`); unknown stock isn't compared.
- **Revenue at stake** is 30 days of Discovery revenue for the product: an upper bound, not a forecast.
- It never outputs `margin`, `cost` or other attributes beyond the six it compares.
- For feed freshness and failed imports, use [data-feed-health](../data-feed-health/).
