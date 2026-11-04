# Splitting a revenue change

How to split a change in revenue into buyers, orders per buyer and order value, so the parts multiply back (as ratios) or add back (in money) exactly.

## The identity

For one period:

- orders per buyer = orders ÷ buyers
- AOV (average order value) = revenue ÷ orders
- so **revenue = buyers × orders per buyer × AOV**, exactly.

Use the raw counts from the queries (revenue, orders, buyers), not rounded rates. "Orders" must be completed orders, counted once each (see the duplicate check in step 4 of the skill). "Buyers" are unique customers with at least one completed order in the period.

## Ratios (the default)

For each measure, ratio = current ÷ previous. Then:

```
revenue ratio = buyers ratio × orders-per-buyer ratio × AOV ratio
```

Multiply the three back together and compare with the revenue ratio. They must agree to three significant figures; if not, one of the six inputs is wrong.

The **main driver** is the ratio furthest from 1 in either direction. Compare `|ln(ratio)|`, so that ×0.80 (ln = −0.22) and ×1.25 (ln = +0.22) count as the same size.

## Money (when the user wants amounts)

Percentage changes don't add up. The log-mean (LMDI) split does:

1. L = (R₁ − R₀) ÷ (ln R₁ − ln R₀). If R₁ = R₀, there's no change to split.
2. buyers part = L × ln(buyers ratio)
3. orders-per-buyer part = L × ln(orders-per-buyer ratio)
4. AOV part = L × ln(AOV ratio)

The three parts add up to R₁ − R₀ exactly. Each part's share of the change = part ÷ (R₁ − R₀). A part can have the opposite sign to the total (AOV down while revenue rises); its share is then negative and the others add up to more than 100%. Say it in words: "lower order value took back 4% of the rise".

If any value is zero (no orders in one period), the split isn't defined: report the change as "new" or "gone".

### Worked example (illustrative numbers)

`scripts/revenue_split.py` does all of this; the numbers below are its output. By hand, work from the raw counts: with the ratios rounded to three decimals the parts come to 287,067, not 287,000.

| | Previous | Current | Ratio |
|---|---|---|---|
| Revenue | 280,000 | 567,000 | ×2.025 |
| Orders | 870 | 1,750 | ×2.0115 |
| Buyers | 810 | 1,510 | ×1.8642 |
| Orders per buyer | 1.0741 | 1.1589 | ×1.0790 |
| AOV | 321.84 | 324.00 | ×1.0067 |

Check: 1.8642 × 1.0790 × 1.0067 = 2.025. ✓

Money: change = 287,000; L = 287,000 ÷ ln(2.025) = 406,763.50.

- buyers: L × ln(1,510 ÷ 810) = +253,344.79 (88%)
- orders per buyer: L × ln(1.15894 ÷ 1.07407) = +30,933.21 (11%)
- AOV: the rest, 287,000 − 253,344.79 − 30,933.21 = +2,722.00 (1%); L × ln(324.00 ÷ 321.84) gives the same to the cent

Sum: 287,000.00. ✓ Reading: "Revenue doubled because almost twice as many people bought; they also ordered a little more often; order value barely moved."

## Periods of different length

Calendar months differ (28 to 31 days), and so do periods cut at "today". Report the plain totals, and add revenue per day for each period and its ratio. If the per-day ratio is within `per_day_tolerance` (in [rules.json](rules.json)) of 1, the "change" is the extra days.

## Breaking a measure down by segment

For any dimension (new vs returning, campaign, source, country):

- **Revenue and orders add up** across segments, so each segment's change ÷ the total change is its share. Include the `null` and `other` rows, and check that the segment changes add up to the total change.
- **Unique buyers don't add up** across segments of an event property (one customer can buy through two sources). They do add up across customer groups that exclude each other, such as retained / reactivated / new.
- A segment that grew faster than the total gained share (mix effect); one that grew at the same rate as the total didn't change the mix. Say which: "every source roughly doubled" means the cause is not one channel.

## Daily shape

From the daily query:

- **Step:** the daily level moves on one date and stays. Name the date and look for what started then (a campaign, a promotion, a price change).
- **Window:** a raised level for a stretch of days, then back. Name both dates.
- **Spikes:** a few days far above the rest. Name them.
- **Even:** the level is different throughout. Points to demand, season or reactivation rather than one event.
- **Gaps or a cut-off:** missing days, or no data after a date. Report these first: they make the comparison unreliable.
