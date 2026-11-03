# Example: attribute value clean-up

Illustrative output. Every product, value and count is invented; the clusters match the script's output on the synthetic test fixtures.

**Prompt:** "Our colour filter shows navy three times. Clean up the attribute values."

---

## Attribute value clean-up: example apparel store, 5 attributes

**Headline:** 17 spellings to change across 22 products in 5 attributes; the biggest is colour, where "Navy" is also sent as "NAVY", "navy blue" and "Nvy".

### By attribute

| Attribute | Distinct values | Clusters | Spellings to change | Products affected | For review |
|---|---|---|---|---|---|
| colors | 11 | 4 | 6 | 10 | 0 |
| sizes | 5 | 2 | 3 | 3 | 0 |
| material | 10 | 2 | 3 | 3 | 1 |
| brand | 4 | 1 | 2 | 3 | 1 |
| length | 7 | 2 | 3 | 3 | 0 |

### Top clusters

| Attribute | Canonical | Other spellings (products) | Confidence | Why |
|---|---|---|---|---|
| colors | Navy (5) | NAVY (3), navy blue (2), Nvy (1) | high | case; synonym table; abbreviation |
| colors | Gray (4) | grey (2) | high | abbreviation or spelling table |
| colors | Black (6) | "black " (1) | high | case, trailing space |
| sizes | XL (3) | X-Large (1), x large (1) | high | synonym table |
| material | Cotton (2) | 100% Cotton (1), cotton (1) | high | removed "100%"; case |
| length | 32in (2) | 32" (1), 81 cm (1) | high / medium | same measurement; 81 cm is within 2% of 32 inches |
| brand | Example Brand (8) | "Example Brand " (2) | high | trailing space |

"Navy" and "Black", "Wool" and "Wood", and "Planters" and "Platters" were kept apart; "99 cm" and "100 cm" were not merged.

### For review (low confidence)

- material: "Polyster" (1) → Polyester: one letter apart. Accept?
- brand: "Exmaple Brand" (1) → Example Brand: two letters swapped. Accept?

### Next steps

1. Feed team: apply `attribute-mapping.csv` at source (17 rows), then re-index. The `canonical` column can be changed to the house style ("Navy", not "NAVY").
2. Filters: run `facet-optimizer` to decide which facets to show; until the feed is fixed, a facet value merge in the dashboard is a stop-gap.
3. Missing values: run `product-data-enhancer` on products with no colour or material.
