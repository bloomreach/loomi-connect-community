# Example: Data Hub collection audit

Illustrative output for a made-up workspace with collections `products`, `products_staging` and `stores`. Every name, number and date is invented.

**Prompt:** "Audit our Data Hub item collections."

---

Workspace `Example Retail`: 3 collections, **4 high, 6 medium, 5 low** (200 product records sampled). Production's identifier `sku` is missing on 4% of records, staging uses a different identifier, and the last items-update job failed.

| # | Priority | Collection (item type) | What's wrong | Fix | Owner | Then |
|---|---|---|---|---|---|---|
| 1 | High | `products` (product) | Identifier `sku` filled on 96% of 200 sampled records | Fix the feed so every record sends it | feed or integration team | `data-feed-health` |
| 2 | High | `products` | The latest items-update job (2026-11-02) failed | Read the job error in Data Hub, fix, re-run | Data Hub administrator | `data-feed-health` |
| 3 | High | `products` vs `products_staging` | Identifiers differ (`sku` vs `item_code`) | Use one identifier configuration | Data Hub administrator | — |
| 4 | High | `products` (product) | `material` is required but absent from the latest import | Find why the feed dropped it | feed or integration team | `data-feed-health` |
| 5 | Medium | `products` (product) | `price` declared Float; 18 of 200 values are text | Send numbers | feed or integration team | — |
| 6 | Medium | `products` vs `products_staging` | `promo_flag` only in staging | Add it to production or remove it | Data Hub administrator | — |
| 7 | Medium | `stores` | Last successful data job 12 days ago | Check the feed schedule | feed or integration team | `data-feed-health` |
| … | | | | | | |
| 15 | Low | `products` (product) | `colour`, `fit` configured but never filled | Remove if unused | Data Hub administrator | — |

**Pairs compared:** `products` vs `products_staging` (product): identifiers, 1 attribute added, 1 retyped, destinations differ (staging feeds nothing, as expected).

**Not checked:** variant-level fill rates; `stores` has no records sample.

Changes are made in Data Hub by the owner named on each row; this audit doesn't change anything.
