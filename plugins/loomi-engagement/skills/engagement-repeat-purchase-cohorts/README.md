# Repeat purchase cohorts

Measures how many first-time buyers in a Bloomreach Engagement project come back for a second order, and when. It first checks how far back purchase history goes, so "first-time" really means first. Then it builds a cohort matrix of repeat purchase rate by first-purchase month, a pooled curve, the time to second order as buckets with approximate quartiles, and the point where second orders slow down, to time a second-purchase campaign. It uses aggregate EQL counts only, and it never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_event_schema`, `estimate_eql_cost`, `execute_analytics_eql` |
| **Other requirements** | Python 3 is optional, for [scripts/cohort_matrix.py](scripts/cohort_matrix.py) (standard library only, no network). Without it, the steps explain the sums by hand. |
| **Tested with** | Claude Code, November 2026: every query run live and read-only against a sandbox project (about 75,000 customers, three years of purchases): the history check, the one-query matrix, monthly and weekly single-cohort counts, and the funnel cross-check. One cohort's counts matched counts worked out from per-customer purchase dates exactly, and the script's approximate quartiles were within a day of the exact ones. Not tested in an OpenAI client. |
| **Maintainer** | @pavelsafarikbr |

## Example prompts

- "How many of our first-time buyers come back?"
- "What's our repeat purchase rate by cohort?"
- "How long does it take a new customer to place a second order?"
- "When should we send the second-purchase email?"
- "Show me a retention cohort matrix for this year's new customers."

See [examples/illustrative-cohorts.md](examples/illustrative-cohorts.md) for an example output. Its names and numbers are illustrative.

## How it works

1. **History check:** customers by the month of their first-ever purchase. The earliest month shows where history starts, and comparing a month's first-ever buyers with all its buyers shows whether "first-time buyer" and "bought that month" would give different answers.
2. **Cohort counts:** one query for the whole matrix of first-ever buyers, or one per cohort for "new or reactivated" and "anyone who bought that month". Each counts customers with a second order by a series of cutoff dates.
3. **Matrix and curve:** [scripts/cohort_matrix.py](scripts/cohort_matrix.py) lines the cohorts up by months since the first order, pools them by size, and reads the quartiles of time to second order and the drop-off point from the curve. Thresholds are in [references/rules.json](references/rules.json).
4. **Cross-check:** a two-step funnel gives the number of repeat buyers and the mean time to second order for the window.

Every query, with its tested status and cost, and the traps found in testing are in [references/eql-patterns.md](references/eql-patterns.md).

## How it differs from other skills

- `winback-opportunity` looks at customers who **stopped** buying, by days since their last purchase and by order count, and sizes the revenue at stake.
- `segment-opportunity-finder` sizes the audiences that are in a repeat window **today** (one-time buyers 15–30 or 31–90 days after their order) and checks whether a flow covers them.
- This skill measures the **behaviour over time**: what share of each month's new buyers come back, how fast, and when the pace drops. That's what sets the windows the other two use.

## Notes and limitations

- EQL has no median or percentiles, so time to second order is read from calendar-month (or weekly) buckets: about ±15 days for monthly cohorts and ±3.5 for weekly ones. Exact figures need per-customer pulls over many calls, which the skill doesn't do.
- A funnel's `within N days` doesn't measure "second order within N days of the first": it matches any two orders. The skill counts orders by cutoff dates instead.
- If purchase history is short, almost everyone looks like a first-time buyer. The skill checks history depth first, and offers "new or reactivated" cohorts when first-ever isn't reliable.
- The cohort month comes from the first purchase event of any status.
