# Price anomaly finder

Finds wrong prices across a whole Bloomreach Discovery catalog (or an Engagement catalog). It compares every product with its own category or product type using robust statistics (median and median absolute deviation on a log scale, never mean and standard deviation), and flags likely unit or decimal errors (×10, ×100, ÷100), outliers, sale prices above or equal to the regular price, discounts beyond a sane maximum, zero, negative and missing prices, variants priced very differently from their siblings, and the same product or title at different prices. Findings are ranked by revenue, views and page-one rank, and each says whether the feed team or the pricing team should fix it. Read-only.

| | |
|---|---|
| **Products** | Discovery (Engagement catalogs as an alternative source) |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `search_discovery_catalogs`, `search_discovery_product_grid_insights`, `get_discovery_product_performance_table`, `get_discovery_query_performance`; for Engagement catalogs `list_cloud_organizations`, `list_projects`, `search_catalogs`, `search_catalog_items` |
| **Other requirements** | Python 3 for `scripts/price_anomalies.py` (standard library only) |
| **Tested with** | Claude Code, November 2026: read-only calls against a Bloomreach demo Discovery account (a 200-row grid page with prices and inline variants, catalog details, an empty product performance table) and one Engagement demo catalog (3 items). The script was run on a real 200-row page and tested on invented fixtures. **Not run end to end** on a full catalog or in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Find wrong prices in our catalog."
- "Are there any prices that look like cents-vs-dollars mistakes?"
- "Which products have a sale price higher than the normal price?"
- "Audit prices in the sofas and rugs categories for outliers."

See [examples/example-report.md](examples/example-report.md) for an illustrative report.

## How it works

1. Fetches every product's price, sale price, product type and inline variant prices from the product grid, 200 at a time (or one category at a time).
2. Reads revenue and views from the product performance table, and optionally page one of the top searches, to rank by exposure.
3. `scripts/price_anomalies.py` groups the products, works out each group's median and quartiles with exact decimal maths, and runs every check, with thresholds in `references/rules.json`. It writes a JSON summary and, with `--csv`, every finding for the feed and pricing teams.

## Notes and limitations

- **Catalog-wide and statistical.** For the products shoppers see first (page one and top sellers, with stock and swatches), use `discovery-variant-health`.
- Groups smaller than `min_group_size` aren't judged for outliers; the report lists them.
- If most products have a sale price equal to the regular price, that's reported once as a feed default, not per product.
- Engagement catalogs: `search_catalog_items` reaches only the first 1,000 items, and there's no performance data, so priorities ignore revenue.
- It never reads or outputs `margin`, `cost` or similar fields, and never asks the grid for them.
