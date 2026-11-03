# Catalog configuration checks

What each check in `scripts/config_audit.py` looks for, why it matters and what to change. Thresholds and word lists are keys in `rules.json`; the text names the key rather than its value.

## Flags in the catalog config

`custom_attributes` give each attribute a `level` (product or variant), a `data_type` (text or number), `facetable` (`off`, `auto` or `manual`), `searchable` and `displayable`. `displayable` means the attribute is returned in API responses, so it reaches the storefront and anyone who reads the page source.

| Check | Priority | When | Change |
|---|---|---|---|
| Internal field exposed | High | An attribute named with an `internal_words` word (margin, cost …) is displayable or facetable | Displayable off, facetable off; keep it only for ranking |
| Internal field exposed | Medium | The same, only searchable | Searchable off |
| Key attribute not searchable | From `must_be_searchable` | `title`, `brand` (high), `description`, `keywords`, `category_names` (medium) are set not searchable in `reserved_attribute_searchability` or `core_attribute_searchability` | Make it searchable |
| Numeric attribute searchable | Medium (custom) / Low (reserved) | A number attribute is searchable, or a `numeric_reserved` one such as price | Searchable off unless shoppers search by it |
| Identifier searchable | Low | A custom attribute named with an `id_words` word is searchable | Keep only if shoppers type codes |
| Duplicates a reserved attribute | Medium | A custom attribute is a reserved name with a `reserved_prefixes` prefix (`product_brand` and `brand`) | Use the reserved one everywhere |

## Variants, index and autosuggest

| Check | Priority | When | Change |
|---|---|---|---|
| Unavailable variant as hero | Medium | `variants.use_unavailable_variant_as_hero` is on | Turn it off unless every variant is always in stock |
| Variant facets without variant filtering | Low | A variant-level attribute is facetable and `variants.enable_filtering` is off | Enable variant filtering if shoppers filter on it |
| Index jobs off | High | `index.enable_index_jobs` is false | Turn index jobs on; hand off to `data-feed-health` |
| Drop threshold | Medium | `index.search_docs_drop_threshold` is above `max_drop_threshold` | Confirm what it means for the account, then lower it |
| Autosuggest start | Low | `autosuggest.minimum_character_count` is above `max_suggest_min_chars` | Lower it; hand off to `autosuggest-audit` |
| Stale or empty index | Medium / High | The production catalog's last refresh is older than `stale_index_days`, or it has 0 products | Hand off to `data-feed-health` |

## Fill rates from the product sample

| Check | Priority | When | Change |
|---|---|---|---|
| Key attribute missing | From `key_reserved` | A key reserved attribute (title, url, thumb_image, price: high) is filled on fewer than `key_min_fill` of sampled products | Fix the feed; hand off to `product-data-audit` |
| Configured but empty | Medium if searchable or facetable, else Low | A configured custom attribute is filled on fewer than `custom_min_fill` of sampled products | Send it, or remove it from the configuration |
| Unconfigured attribute | Low | A feed attribute is neither configured, reserved nor a `core_fields` field | Configure it if shoppers should search or filter on it |

Empty strings, empty lists and nulls count as not filled. With fewer than `min_sample` products the fill rates are rough, and the report says so.

## Not covered

- **Range facets:** the config has no range setting; numeric facets are reviewed by `facet-optimizer`.
- **Which facets show where:** `facet-optimizer`.
- **Feed and index job history:** `data-feed-health`.
