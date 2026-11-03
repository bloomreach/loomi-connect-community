# Discovery product report

How one product is doing everywhere in Bloomreach Discovery: its last 30 days against its category peers and the period before, where it ranks across its top search queries and its category pages, which merchandising rules boost, pin, bury or exclude it, its catalog data and variant stock, and the three most useful next actions with the skill to hand each one to.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `get_discovery_product_performance`, `get_discovery_product_performance_table`, `get_discovery_query_performance`, `search_discovery_product_grid_insights`, `search_discovery_catalog_products`, `search_discovery_catalog_product_variants`, `list_discovery_sites`, `get_ranking_rule` |
| **Other requirements** | Python 3 for `scripts/product_report.py` (standard library only) |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## Example prompts

- "How is the Jersey Midi Dress doing?"
- "Give me a report on product 110726: where does it rank, and which rules touch it?"
- "Is this product worth promoting more?"

## How it works

1. Reads the product's 30-day performance and, from the performance table, the period before.
2. Reads its catalog record and variants for availability, stock and missing fields.
3. Fetches its category's grid and the grids of its most relevant top queries (at most `max_query_grids`), and the performance of up to `max_peer_lookups` peers from the category's page one (both in `references/rules.json`).
4. `scripts/product_report.py` compares it with its peers, finds its position on every grid (banners skipped), lists the rules that name it, and ranks the next actions.

See [examples/product-report.md](examples/product-report.md).

## Notes and limitations

- There's no per-product query breakdown in Discovery, so positions cover the top queries checked, not every query.
- Peers are the products on its category's page one, which skews towards strong products.
- The grid shows a default shopper: audience-targeted rules and personalisation can rank it differently.
- Commercial fields such as `margin` and `cost` are never shown.
