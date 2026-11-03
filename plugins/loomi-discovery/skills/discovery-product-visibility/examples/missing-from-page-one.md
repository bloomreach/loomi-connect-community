# Example: a product off page one

Synthetic example. The account, products and rule IDs are made up.

**Prompt:** "Why isn't the Wool Coat (P10) on page one for 'rain jacket'?"

**Calls made, one at a time:**

1. `search_discovery_product_grid_insights`: query "rain jacket", `rows=200`, `fl="pid,title,brand"`, `facet=false`. Saved to `grid-1.json`; the product is there, so no further grid calls were needed.
2. `search_discovery_catalog_products`: `product_id="P10"`. Saved to `catalog.json`.

```bash
python3 <this skill's folder>/scripts/visibility_explain.py --pid P10 --grid work/grid-1.json --catalog work/catalog.json --query "rain jacket" --out work/visibility.json
```

## Why "Wool coat" (P10) ranks #13 for "rain jacket"

**Verdict:** Three products are pinned above it by rule 900001, and its text doesn't mention "rain" or "jacket", so its text match is less than half that of the products around it. Fix the product text first.

| | This product | Median of products above |
|---|---|---|
| Position | #13 of 60 (page one: yes, but below the fold) | — |
| Relevance (text match) | 30.0 | 87.7 |
| Performance | 490 | 496.5 |

**Causes**
1. **Merchandising**: 3 products above it are pinned by rule 900001 (`boost_top_products`). Fix: if P10 should lead, add it to that rule; check the change with `discovery-change-qa` before switching it on.
2. **Data**: a weaker text match than the products above it (relevance 30.0 against a median of 87.7); the title doesn't match the query. Its title, description and categories don't contain "jacket" or "rain". Fix: if it is a rain jacket, say so in the title (`product-data-enhancer`); if it isn't, it's ranking about right.

**Rules in play:** 900001 pins 3 products and excludes category `cat-x`.
**Couldn't check:** personalised ranking for real shoppers; any facet filters they pick.
**Next:** `product-data-enhancer` for the product text.
