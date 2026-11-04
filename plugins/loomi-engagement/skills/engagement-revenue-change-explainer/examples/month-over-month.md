# Example: month over month (anonymised)

**Based on a real read-only test run** on a sandbox project in November 2026. Numbers are rounded to three significant figures and campaign names are relabelled; the shape of the answer is what the skill returned. 16 queries and 5 cost estimates, about 8 minutes including waits for the shared EQL rate limit.

**Prompt:** "Revenue roughly doubled in July compared with June. Why?"

---

**Revenue up ×2.03 (+103%)** (1–30 June → 1–31 July 2026, UTC; the project reports in UTC): almost twice as many people bought, most of them past customers who hadn't bought in June. The rise starts on 8 July and fades from 29 July.

| | June | July | Ratio |
|---|---|---|---|
| Revenue | $2.79M | $5.67M | ×2.03 |
| Orders | 8,740 | 17,500 | ×2.00 |
| Buyers | 8,100 | 15,100 | ×1.86 |
| Orders per buyer | 1.08 | 1.16 | ×1.07 |
| AOV | $320 | $324 | ×1.01 |
| Revenue per day | $93.1k | $183k | ×1.96 |

**Split:** revenue ×2.03 = buyers ×1.86 × orders per buyer ×1.07 × AOV ×1.01. In money (from `revenue_split.py`): buyers +$2.53M (88%), orders per buyer +$0.29M (10%), order value +$0.06M (2%), adding up to the +$2.88M change.

**What drove it: who bought**
| Buyers | June | July | Change | Share of buyer growth |
|---|---|---|---|---|
| Retained (also bought the month before) | 1,200 | 2,060 | +860 | 12% |
| Reactivated (bought before, not the month before) | 6,880 | 13,000 | +6,120 | 87% |
| New (first purchase ever) | 20 | 32 | +12 | 0.2% |

**What drove it: campaign attribution**
| Segment | June | July | Change | Share of the change |
|---|---|---|---|---|
| No campaign attributed | $2.12M | $4.15M | +$2.03M | 71% |
| Monthly newsletter (onsite + email) | $0.32M | $0.95M | +$0.63M | 22% |
| Other attributed campaigns | $0.35M | $0.57M | +$0.22M | 8% |

Every purchase source (web, mobile web, app) roughly doubled, so the rise isn't one channel.

**Shape:** about $90k a day until 7 July; a step to $190k–260k a day from 8 to 28 July; about $120k a day from 29 July.
**Data checks:** history starts in 2023, well before June (new vs returning is reliable). No missing days in either month. All purchases have the completed status; no order ID repeats in the window. One currency (all orders in USD). The item-level purchase event only starts in August, so category couldn't be split.
**Definitions:** order = `purchase` event with `purchase_status = "success"`; revenue = sum of `total_price` (one currency); buyer = unique customer with at least one such order in the month; new buyer = first-ever purchase in the month.
**Queries run** (16, as of 2026-11-03 14:20 UTC), for example:

    select sum event purchase.total_price, count event purchase, count first event purchase by event purchase.purchase_status grouping top 10 with null since 2026-07-01T00:00:00Z until 2026-08-01T00:00:00Z

**Not checked:** category (no item-level data for the period), device (not on the purchase event).
**Next:** the step on 8 July lines up with the monthly newsletter, which is only 22% of the rise by attribution. `engagement-campaign-digest` can show what was sent between 8 and 28 July.
