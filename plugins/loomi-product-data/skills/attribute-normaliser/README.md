# Attribute normaliser

Finds inconsistent spellings of the same attribute value across a Bloomreach Discovery catalog (or an Engagement catalog): "Navy", "navy blue", "NAVY" and "Nvy"; "XL" and "X-Large"; "100% Cotton" and "cotton"; "32in", '32"' and "81 cm". It covers the attributes that drive filters and search (colour, size, material, brand, gender, fit, and any facet or ranking-rule attribute), groups the spellings into clusters with a proposed canonical value and product counts, flags low-confidence clusters for review, and writes a CSV mapping file for the feed team. It never merges values that are genuinely different, and it changes nothing in Bloomreach.

| | |
|---|---|
| **Products** | Discovery (Engagement catalogs as an alternative source) |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `search_discovery_catalogs`, `list_facet_attributes` (via `search_tools` / `call_tool`), `list_facets_global`, `list_site_search_facets`, `list_category_facets`, `get_facet_rule`, `list_ranking_rules_global`, `list_site_search_ranking_rules`, `search_discovery_product_grid_insights`; for Engagement catalogs `list_cloud_organizations`, `list_projects`, `search_catalogs`, `search_catalog_items` |
| **Other requirements** | Python 3 for `scripts/attribute_clusters.py` (standard library only) |
| **Tested with** | Claude Code, November 2026: read-only calls against a Bloomreach demo Discovery account (the facetable attribute list, the grid's facets with and without a raised `facet.limit`, product pages with attribute and variant fields) and one Engagement demo catalog. The script was run on the real facet response and tested on invented fixtures. **Not run end to end** in a fresh session or in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Our colour filter shows navy three times. Can you clean up the values?"
- "Normalise the size, colour and material values in our catalog."
- "Give the feed team a mapping file for inconsistent attribute values."
- "Which brand names are spelled more than one way?"

See [examples/example-apparel.md](examples/example-apparel.md) for an illustrative output.

## How it works

1. Picks the attributes that matter: the facetable text attributes, plus any named in facet and ranking rules.
2. Reads every value with its count from one product grid call with facets on (`facet.limit` raised so long value lists aren't cut at 200), and product pages for attributes that aren't facets.
3. `scripts/attribute_clusters.py` folds case, spacing, punctuation, accents and word order, applies the synonym and abbreviation table in `references/value-synonyms.json`, converts measurements, and joins one-word typos only when the rarer spelling is rare. Every row says why it was joined and how confident the join is.
4. Writes the mapping CSV (formula-escaped) and a JSON summary.

## Notes and limitations

- **Review the low-confidence rows.** Typo merges are flagged; testing on a demo catalog showed why the guards exist ("planters" and "platters", "globes" and "gloves", "scented wax" and "unscented wax" are one letter or one prefix apart, and stay apart).
- The proposed canonical value is the most-used spelling, not a house style; the team can change the `canonical` column.
- Facet counts can count variants rather than products (colour especially), so product counts from facets are approximate.
- Attributes marked `stored: false` can't be read from product pages, only from facets.
- The synonym table is deliberately small and conservative. Add account-specific pairs to `references/value-synonyms.json` only when they mean the same thing for every product.
- Related: [facet-optimizer](../../../loomi-discovery/skills/facet-optimizer/) for which filters to show, [product-data-enhancer](../product-data-enhancer/) for missing values.
