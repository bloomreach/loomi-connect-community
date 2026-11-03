# Example: catalog parity check

**This example is illustrative.** The products, IDs and numbers are made up; the shape follows the script's output on synthetic fixtures.

**Prompt:** "Our recommendation emails keep featuring things we've sold out of. Do the Discovery and Engagement catalogs match?"

## Catalog parity: example_outdoor (Discovery, production) vs Example Store / products (Engagement), checked 2026-11-03

**ID mapping:** Discovery `pid` = Engagement item ID, trimmed and case-insensitive. **Sample:** 52 priority (top 30 sellers, page one of 3 searches) + 40 random from Discovery (8 pages of 5, spread across the catalog) + 20 Engagement items (spread over the first 1,000; not random).

**Headline:** 12.5% of products disagree on stock, nearly all out of stock on the site but in stock in Engagement: the Engagement import runs weekly, the site feed hourly.

| Check | Discovery random sample | Rate (95% interval) | Top products |
|---|---|---|---|
| Missing in Engagement | 2 of 40 | 5.0% (1.4–16.5%) | 0 of 30 top sellers |
| Missing in Discovery (Engagement side, not random) | 4 of 20 | 20.0% (8.1–41.6%) | — |
| Stock: out on site, in stock in Engagement | 5 of 40 | 12.5% (5.5–26.1%) | 4 of 52 |
| Price | 3 of 40 | 7.5% (2.6–19.9%) | 2 of 52 |
| Sale price | 1 of 40 | 2.5% (0.4–12.9%) | 3 of 52 |
| URL | 0 of 40 | 0.0% (0.0–8.8%) | 0 of 52 |
| Image / title | 1 / 2 of 40 | 2.5% / 5.0% | — |

### Fix first (by revenue at stake)
| # | Product | Sample | Problem | Discovery | Engagement | Revenue (30 days) |
|---|---|---|---|---|---|---|
| 1 | Rain Jacket (P200) | top seller | Out of stock on site, in stock in Engagement | out of stock | stock_level 12 | $8.0k |
| 2 | Trail Runner Shoe (P100) | top seller, page one "running shoes" | Sale price only in Discovery | $99 | none | $12.0k |
| 3 | Wool Socks (P300) | top seller | Price | $15.00 | $18.50 | $3.0k |
| 4 | 4 random items, e.g. Discontinued Stove (OLD1) | random | In Engagement, not on the site | — | in stock | — |

**Not checked:** 1 top seller (P400) wasn't looked up in Engagement.
**Next steps:**
1. Run the Engagement catalog import daily, or at least update stock and price daily (developer / feed owner). Check both feeds' freshness with `data-feed-health`.
2. Add an in-stock filter to the recommendation engines used in emails (CRM); `recommendation-model-audit` lists them.
3. Remove or flag discontinued items in the Engagement import (developer).
