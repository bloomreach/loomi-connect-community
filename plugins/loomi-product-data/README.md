# loomi-product-data

Skills that improve **product data** for search engines, AI answers and your own site, using Loomi Connect:

- **SEO:** classic search engines and rich results.
- **AEO:** answer engines, featured snippets and voice answers.
- **GEO:** generative AI assistants and AI shopping answers.

The skills read product data from Bloomreach Discovery, or optionally from an Engagement catalog. They weigh it against what shoppers actually search for. The enhancer also uses the assistant's vision to look at product images.

| Skill | What it does | Access |
|---|---|---|
| [product-data-audit](skills/product-data-audit/) | Ranks which products and categories most need better data for SEO, AEO and AI search | Read-only |
| [product-data-enhancer](skills/product-data-enhancer/) | Suggests better product content, attributes, alt text and schema markup from images and data | Read-only |
| [price-anomaly-finder](skills/price-anomaly-finder/) | Wrong prices across the whole catalog: unit and decimal errors, category outliers, sale above price, deep discounts, variant and duplicate conflicts | Read-only |
| [attribute-normaliser](skills/attribute-normaliser/) | Clusters inconsistent attribute values ("Navy", "navy blue", "Nvy") and writes a canonical-value mapping file for the feed team | Read-only |

Start with the audit to find where the gaps are, then run the enhancer on the products it ranks highest. The price anomaly finder and attribute normaliser catch wrong prices and messy values that break filters and trust.

All four skills only make suggestions. They never change the catalog. The enhancer writes its suggestions as JSONL, one product per line, which converts into a CSV, schema.org JSON-LD files and a review sheet. Your team reviews them and imports them through its usual catalog process.

To add a skill, see [CONTRIBUTING.md](../../CONTRIBUTING.md).
