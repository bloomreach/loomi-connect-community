# Breakdown maths

How `scripts/decompose_change.py` splits a change so the parts add up. Use this when you can't run the script, or to explain the method to a user.

## The identity

For any card or table row:

- conversion rate (CR) = orders ÷ visits
- average order value (AOV) = revenue ÷ orders
- so **revenue = visits × CR × AOV**, exactly.

Use the raw counts (`visits`, `conversions`, `revenue`) from the response, not the rounded percentage strings. "Conversions" are orders.

## Splitting a change into traffic, conversion and order value

Simple percentage changes don't add up: −2.9% visits, +0.1% CR and −0.9% AOV don't sum to −3.7% revenue. Use the log-mean (LMDI) split, which does:

1. L = (R₁ − R₀) ÷ (ln R₁ − ln R₀). If R₁ = R₀, L = R₀.
2. traffic part = L × ln(visits₁ ÷ visits₀)
3. conversion part = L × ln(CR₁ ÷ CR₀)
4. order-value part = L × ln(AOV₁ ÷ AOV₀)

The three parts sum exactly to R₁ − R₀. Each part's **share of the change** is part ÷ (R₁ − R₀). A part can have the opposite sign to the total (for example conversion up while revenue falls); its share is then negative, and the others add up to more than 100%. Say so in words: "conversion rose slightly, offsetting 3% of the drop".

If any value is zero (a new query with no previous orders, or one that disappeared), the split isn't defined. Report the whole row change as "new" or "gone".

### Worked example (example_apparel, 7 days)

| | Previous | Current |
|---|---|---|
| Revenue | $7,927,881 | $7,630,956 |
| Visits | 106,648 | 103,523 |
| Orders | 53,879 | 52,357 |

Change = −$296,925. L = −296,925 ÷ ln(7,630,956 ÷ 7,927,881) ≈ 7,778,474.

- traffic: L × ln(103,523 ÷ 106,648) ≈ −$231,331 (78%)
- conversion: L × ln(0.50575 ÷ 0.50520) ≈ +$8,438 (−3%)
- order value: L × ln(145.75 ÷ 147.14) ≈ −$74,032 (25%)

Sum: −$296,925.

## Splitting by channel, device and row

These are simple differences, so they add up by construction:

- **Channel:** search Δ + category Δ + other Δ = overall Δ, where other = overall − search − category. Search and category visits overlap, so "other" is an approximate remainder, not a real channel.
- **Device:** desktop Δ + mobile Δ + tablet Δ should equal overall Δ. Report any gap as "unexplained".
- **Rows:** each query's Δ is its share of the search Δ; each category's of the category Δ; each product's and brand's of the overall Δ. The rows you fetched won't cover everything: report the **long-tail remainder** (parent Δ − sum of fetched rows' Δ).

Each channel, device or row can then be split into traffic, conversion and order value in the same way. The row's **main driver** is the part with the largest absolute value.

## Is it more than noise?

The thresholds below are named by their key in [rules.json](rules.json), which `scripts/decompose_change.py` reads; take the values from there.

From the daily trend:

1. Gap for each day = current day − the previous-period day the same number of days earlier as the period length (so the same weekday for 7-day multiples). **Pair by date, not by position:** `get_discovery_trend` leaves out days with no data, so the lists can be different lengths. Treat a missing or $0 day as a data gap, not as a real fall.
2. Total gap = sum of daily gaps = the card change.
3. Noise band ≈ standard deviation of the previous period's daily values × √(number of days). With fewer than `noise_min_days` days of data, the noise is unknown.
4. **change ÷ noise band** below `noise_normal_ratio`: within normal variation; below `noise_borderline_ratio`: borderline; at or above it: larger than normal.

This is a rough guide, not a significance test. Weekday patterns inflate the standard deviation, which makes the test conservative.

## Dating the change

- **Data gaps:** any missing or $0 day. Report these first; they make the rest unreliable.
- **Step:** the split point (with at least `step_min_side_days` days each side) where the mean daily gap shifts most. Report it only if the shift is at least `step_shift_sd_multiple` times the scatter of the days around their side's mean, and the period has at least `step_min_days` days.
- **Concentrated:** the fewest days that make up at least `concentrated_share` of the change, when they are no more than one in `concentrated_max_days_divisor` days of the period (at least one day). Look at what happened on those dates, and on the matching comparison dates.
- **One-off days:** days whose gap is more than `outlier_spread_multiple` median absolute deviations from the median daily gap.
- **Spread evenly:** none of the above.

With only 7 days, a step is weak evidence. Look at a 28-day trend before naming a date with confidence.
