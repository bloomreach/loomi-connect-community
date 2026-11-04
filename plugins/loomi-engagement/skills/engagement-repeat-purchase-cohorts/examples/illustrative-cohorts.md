# Example: repeat purchase cohorts (illustrative)

**This example is illustrative.** The method, the queries and the tool behaviour come from a live, read-only test run, but the project and every number have been invented. The tables are the bundled script's real output for these invented counts. Nothing was created or changed.

**Prompt:** "How many of our first-time buyers come back for a second order, and when should we nudge them?"

**Assistant (before querying):** Purchase history in this project starts in August 2023, so a first-time buyer in 2026 really is first-time. About 2,100–3,100 customers a month placed their first-ever order this year, out of 9,000–12,000 buyers a month. I'll use first-ever buyers from March to August 2026, count completed orders only (`purchase_status` = `success`), and follow them to 30 September, the last complete month. That's one query for the whole matrix plus one cross-check, both rated medium. OK?

**User:** Yes.

---

## Repeat purchase cohorts: Example Store (production), as of 2026-10-02

**Verdict:** About 21% of first-time buyers order again by the end of the month after their first order, and about 47% within six months. Second orders come fastest in the first six weeks and slow to half that pace from month 3 (around day 75), so nudge first-time buyers around day 20 and again before day 50.

### Cohort matrix: share with a second order by the end of month k

| First order in | Buyers | M0 | M1 | M2 | M3 | M4 | M5 | M6 |
|---|---|---|---|---|---|---|---|---|
| March | 2,400 | 8.1% | 21.4% | 30.5% | 36.8% | 41.0% | 44.2% | 46.6% |
| April | 2,100 | 8.4% | 21.1% | 30.6% | 36.7% | 41.1% | 44.2% | |
| May | 2,600 | 7.9% | 21.1% | 30.5% | 36.5% | 40.7% | | |
| June | 2,300 | 8.3% | 21.2% | 30.8% | 36.9% | | | |
| July | 3,100 | 8.5% | 21.1% | 30.5% | | | | |
| August | 2,700 | 8.2% | 21.3% | | | | | |
| **Pooled** | 15,200 | 8.2% | 21.2% | 30.6% | 36.7% | 41.0% | 44.1% | 46.5% |

M0 is the rest of the first-order month; M1 is the month after, and so on. The cohorts behave almost identically, so the curve is stable rather than a one-month effect.

### Time to second order

| Bucket | Second orders (share of cohort) | Pace per month | Share of repeaters |
|---|---|---|---|
| M0 (about days 0–15) | 8.2% | 16.5% | 18% |
| M1 (days 15–46) | 13.0% | 13.0% | 28% |
| M2 (days 46–76) | 9.4% | 9.4% | 20% |
| M3 (days 76–107) | 6.1% | 6.1% | 13% |
| M4 | 4.3% | 4.3% | 9% |
| M5 | 3.2% | 3.2% | 7% |
| M6 | 2.4% | 2.4% | 5% |

Quartiles (approximate, ±15 days): 25% by day 23, median day 52, 75% by day 97, among those who came back within about 200 days. Mean from the funnel for March–September: 58 days (all buyers in the window, so a little lower than a cohort's).

### When to nudge

Second orders come fastest in the first six weeks (peak pace in M0 and M1), then slow to half that pace or less from M3, after about day 75. A quarter of second orders arrive by day 23 and half by day 52.

- **First nudge around day 20** to first-time buyers without a second order: recommendations based on the first order, no discount.
- **Second nudge around day 45–50**, before the median and well before the slowdown: an incentive for those still without a second order.
- After about day 90, treat them as lapsing and hand them to win-back.

**Definitions:** cohort = first-ever completed order in the month (history starts August 2023); purchase = the `purchase` event with `purchase_status` = `success`; data to 30 September 2026; months in UTC.
**Queries:** 3 EQL queries (history check, cohort matrix, funnel cross-check), all medium. **Checks:** cumulative counts grow at every cutoff; the funnel's repeat buyers equal the count of customers with 2+ orders in the same window.

**Next:** see how many of today's first-time buyers are in the day 20–50 window, and whether a flow already covers them, with `segment-opportunity-finder`; build the audience with `engagement-segment-builder`; draft the two-step flow with `engagement-scenario-builder`.
