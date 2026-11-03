# Discovery variant health

Checks variant (SKU) and stock health for the Bloomreach Discovery products that matter most: the products on page one of the top searches and categories, and the top sellers. It finds out-of-stock products that still rank or sell, zero or wrong prices, duplicate SKUs, missing swatches and thumbnails, broken image URLs and thin colour ranges, and returns a prioritised list with the revenue at stake and who should fix each one.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `get_discovery_product_performance_table`, `search_discovery_product_grid_insights`, `search_discovery_catalogs`, `search_discovery_catalog_products`, `search_discovery_catalog_product_variants` (through `search_tools` / `call_tool`) |
| **Other requirements** | Python 3 for `scripts/variant_health.py` (standard library only) |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## Example prompts

- "Are any of our top products out of stock but still on page one?"
- "Check the variants of our best sellers: missing swatches, wrong prices, duplicate SKUs."
- "Which products on page one for 'dress' have broken images or zero prices?"

## How it works

1. Picks the top searches (and optionally categories) by revenue, and the top sellers.
2. Saves page one of each search from the live grid, with each product's inline variants (prices and images).
3. Fetches each product's catalog record (product-level stock, prices, thumbnail) and its variant records (per-variant stock, colour, prices and images).
4. `scripts/variant_health.py` joins them and runs every check, with thresholds and word lists in `references/rules.json`.

See [examples/example-report.md](examples/example-report.md) for an illustrative report.

## Notes and limitations

- **Stock depends on the catalog's fields.** The script reads the first of the stock fields listed in `rules.json` (`availability`, `stock_level` and similar). If the catalog has none, stock isn't checked and the report says so. "Unknown" stock counts as neither in nor out.
- **The grid drops stock fields.** On the demo account the grid ignored `availability` and `stock_level` in `fl`, so stock comes from catalog records, one call per product.
- **Image checks are static**: `http://`, no scheme, or a placeholder host or word. The skill doesn't load images.
- It never outputs `margin`, `cost` or other catalog attributes beyond those it checks.
