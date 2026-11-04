# Example: voucher pool health (illustrative)

**This example is illustrative.** The method and the kinds of finding come from read-only runs against a demo Engagement project, but the project, pool and campaign names and every number have been invented.

**Prompt:** "Will any of our voucher pools run out before Black Friday?"

## Voucher pool health: example-retail-prod, 4 November 2026 (next 30 days)

**Verdict:** 3 of 7 pools are red. "Welcome 10" runs out in about 5 days at the welcome flow's current pace, and the Black Friday email needs more codes than "Black Friday 20" has, which also expire a week before it sends.

| Pool | Available / total | Codes a day (source) | Days of cover | Next planned send (audience) | Expiry | Rating |
|---|---|---|---|---|---|---|
| Welcome 10 | 5 / 60 | 1.0 (code assignment times) | 5 | — (event-triggered flow) | — | Red |
| Black Friday 20 | 150 / 200 | 1.0 (change in available codes, 10 days) | 150 | 27 Nov, Black Friday email (~180) | 20 Nov | Red |
| Spring 15 | 0 / 10 | — | 0 | — | — | Red |
| VIP | 250 / 300 | not measured | — | — | — | Unknown |
| Partial | 40 / 100 | at least 0.36 (first page of codes only) | up to 112 | — | — | Green |

### Findings
1. [High] Welcome 10: about 5 days of cover at 1 code a day → import more codes this week, or point the welcome flow at another pool.
2. [High] Black Friday 20: the 27 Nov send reaches about 180 customers, but 150 codes are left → import at least 30 more codes, or narrow the audience.
3. [High] Black Friday 20: codes expire on 20 Nov, before the 27 Nov send → extend validity or swap the pool.
4. [High] Spring 15: empty, but the "Spring pop-up" weblayer is active and still hands out its codes → switch the weblayer off or refill the pool.
5. [Medium] VIP: used by an active flow, but no burn rate could be measured → load its codes or compare with next week's available count.

**Not in use:** "Old pool" (nothing references it; review before deleting). "Loyalty 5" (only an archived scenario uses it).
**How this was measured:** burn window 28 days; all 60 codes of Welcome 10 counted; 1 of 10 pages of Partial; 12 scenarios and 4 emails searched with designs, the rest through `used_by`; calendar read in 5 weekly calls; SMS campaigns not checked (no access).
