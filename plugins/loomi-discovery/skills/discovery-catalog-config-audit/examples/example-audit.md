# Example: catalog configuration audit

Illustrative output for a made-up catalog `acme_store`. Every attribute name, number and setting is invented.

**Prompt:** "Audit our Discovery catalog configuration."

---

Catalog `acme_store`: **3 high, 6 medium, 4 low** (150 products sampled). An internal margin field is returned to the storefront, brand isn't searchable, and 8% of products have no image.

| # | Priority | Attribute or setting | What's wrong | Change to make | Then |
|---|---|---|---|---|---|
| 1 | High | `unit_margin` | Internal data, displayable and facetable: it's in every API response | Displayable off, facetable off | — |
| 2 | High | `brand` | Not searchable, so "northwind jacket" can't match on brand | Make brand searchable | `discovery-search-health` |
| 3 | High | `thumb_image` | Missing on 8% of sampled products | Fix the feed | `product-data-audit` |
| 4 | Medium | `product_brand` | Duplicates the reserved `brand`; the brand facet uses `product_brand`, ranking uses `brand` | Use `brand` everywhere | `facet-optimizer` |
| 5 | Medium | `variants.use_unavailable_variant_as_hero` | Out-of-stock colours can be shown as the product image | Turn it off | — |
| 6 | Medium | `pack_weight` | Number attribute is searchable, so "500" matches unrelated products | Searchable off | — |
| 7 | Medium | `index.search_docs_drop_threshold` | Set to 100: a feed that drops every product would still be indexed | Confirm, then lower | `data-feed-health` |
| 8 | Medium | `fit` | Facetable and searchable, but no sampled product has it | Send it, or remove it | `product-data-audit` |
| … | | | | | |
| 11 | Low | `price`, `sale_price` | Searchable numbers | Review | — |
| 12 | Low | `loyalty_points` | In the feed, not configured | Configure only if needed | — |

**Not checked:** range facet settings (not in the config; see `facet-optimizer`).

Changes are made in the Discovery dashboard under the catalog's attribute settings; a reindex may be needed before they take effect.
