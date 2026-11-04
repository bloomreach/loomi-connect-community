# Scoring survey answers by hand

`scripts/survey_insights.py` does all of this. Use this page when scripts can't run, and show the working for at least one score. Thresholds are keys in [rules.json](rules.json); `z` is the two-sided normal quantile for `confidence`.

## Response rate

- **Respondents** = customers with any survey event for the survey in the window (pattern S1).
- **Response rate** = respondents ÷ customers shown or sent the survey (pattern S6). Without a denominator there's no rate: say so.
- **Close rate** = customers who closed it without answering ÷ customers shown, where tracked.
- **Answered share** of a question = its survey events (S2) ÷ respondents. A recurrent survey can push it above 100%: report it, and say customers may have answered more than once.
- **Drop-off** = answers to the last question ÷ answers to the first.

## Interval for a share (Wilson)

For `k` out of `n`, with `p = k ÷ n`:

```
centre = (p + z²/2n) ÷ (1 + z²/n)
half   = z × √(p(1−p)/n + z²/4n²) ÷ (1 + z²/n)
interval = centre ± half, kept between 0 and 1
```

Use it for response and close rates, each answer's share, and CSAT.

## NPS-style score

For a rating question whose star count is in `nps_star_counts`:

- promoters: answer ≥ `nps_promoter_min`; passives: ≥ `nps_passive_min` and below promoters; detractors: the rest.
- `n` = promoters + passives + detractors (unreadable answers left out).
- score = (promoters − detractors) ÷ n × 100.
- With `p` and `d` the promoter and detractor shares: standard error = √((p + d − (p − d)²) ÷ n) × 100; interval = score ± z × that, kept between −100 and +100.

Engagement's 10-star question runs **1 to 10**, with no 0. Label the result "NPS-style score (1–10 stars)", and don't compare it with published 0–10 NPS benchmarks without saying so.

Worked example: 110 promoters, 30 passives, 60 detractors (n = 200). Score = (110 − 60) ÷ 200 × 100 = +25. p = 0.55, d = 0.30, se = √((0.85 − 0.0625) ÷ 200) × 100 = 6.27; with z = 1.96, interval 25 ± 1.96 × 6.27 = +12.7 to +37.3.

## CSAT

For a rating question whose star count is a key in `csat_top_box`: satisfied = answers in the top N boxes (N is the value); CSAT = satisfied ÷ answers, with a Wilson interval. Report the average star rating too.

## Trust

- Fewer answers than `min_responses`: **too few to trust**. Show the score, labelled, and don't act on it.
- Fewer than `small_sample`: **small sample**. Give the interval with the score.
- Two scores (weeks, splits) differ only when their intervals don't overlap; otherwise say "no clear difference". Split groups with fewer than `min_split_group` customers are shown but not compared.

## Weekly trend

Add daily counts into weeks counted from the window's first day (week 1 = days 1–7, and so on). Day buckets are Unix seconds at local midnight in the project's time zone, and the bucket hour alone can't tell, say, UTC+13 from UTC−11. **Pass the offset from the project's time zone** (`--utc-offset-minutes`, from −720 to 840), **or leave it out and the script anchors the first day bucket on `--since`** and counts whole days from there; that needs answers on the window's first day, so pick `--since` as the first day with answers when you have no offset. The week containing today is still collecting answers, so the default window ends yesterday. A week cut short by the window's end isn't a full week; don't compare it. A drop is judged only with at least `trend_min_full_weeks` full weeks, and is flagged when the latest full week is below `trend_drop_share` of the median of the earlier full weeks, and that median is at least `trend_min_weekly`.
