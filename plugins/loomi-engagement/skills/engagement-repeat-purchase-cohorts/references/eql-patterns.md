# EQL patterns for repeat-purchase cohorts

Every query here returns **aggregate counts**. None of them lists or reads individual customers.

Status labels:
- **Ran:** executed with `execute_analytics_eql` in live, read-only testing (November 2026) against a sandbox project with about 75,000 customers, 23 million events and purchase history going back about three years.
- **Parsed:** accepted by `estimate_eql_cost`, not executed.

Replace `purchase`, `purchase_status` and `"success"` with the project's own order-level purchase event, status property and completed-order value, from `get_event_schema`. Always add `Z` to dates.

## H1. Customers by first-purchase month: where history starts (Ran, `medium`)

```
select count customers by customer first event purchase timestamp grouping top 60 format year month customers matching exists[event purchase]
```

- Row headers are the start of each month in Unix seconds, in the project's time zone. Each row is the number of customers whose **first-ever** purchase fell in that month.
- **The earliest row is the start of history, and it's inflated**: everyone who bought before tracking or the import began lands there. In testing it was the largest month in three years.
- The monthly rows matched first-ever buyer counts from separate queries exactly (for example 36 in one month and 32 in another).
- `first event purchase` is the first purchase of **any** status. If the project records cancelled or failed orders as purchases, say that the cohort month may come from one.
- Keep `grouping top N` at least as large as the number of months of history, or the oldest months fall into `other`.

## C1. Cohort matrix for first-ever buyers, one query (Ran, `medium`)

```
select count customers,
  count customers matching count[event purchase where .purchase_status = "success" until 2026-04-01T00:00:00Z] >= 2,
  count customers matching count[event purchase where .purchase_status = "success" until 2026-05-01T00:00:00Z] >= 2,
  count customers matching count[event purchase where .purchase_status = "success" until 2026-06-01T00:00:00Z] >= 2,
  count customers matching count[event purchase where .purchase_status = "success" until 2026-07-01T00:00:00Z] >= 2,
  count customers matching count[event purchase where .purchase_status = "success" until 2026-08-01T00:00:00Z] >= 2,
  count customers matching count[event purchase where .purchase_status = "success" until 2026-08-19T00:00:00Z] >= 2
by customer first event purchase timestamp grouping top 12 format year month
customers matching exists[event purchase] and not exists[event purchase until 2026-02-01T00:00:00Z]
```

(Shown on several lines for reading; send it as one line.)

- The `not exists[... until <first cohort month>]` limits the rows to first purchases from that month on. Rows after the last complete month are partial cohorts: leave them out or mark them.
- Each `count[...] >= 2` counts orders from the start of history up to the cutoff (exclusive). For first-ever buyers that's the same as counting from their first order.
- Cutoffs: the 1st of every month from the end of the first cohort month, plus the last day with data. A cutoff before a cohort's month ends gives 0 for that row: ignore it.
- In testing, one row's count by the end of June matched an earlier, separately written count of the same cohort (21 of 36).
- Rated `medium` (32) with six cutoffs.

## C2. One cohort, any definition (Ran, `medium`)

```
select count customers,
  count customers matching count[event purchase where .purchase_status = "success" since 2026-03-01T00:00:00Z until 2026-04-01T00:00:00Z] >= 2,
  count customers matching count[event purchase where .purchase_status = "success" since 2026-03-01T00:00:00Z until 2026-05-01T00:00:00Z] >= 2,
  ...
by customer.<low_cardinality_property> grouping top 3 with null
customers matching exists[event purchase where .purchase_status = "success" since 2026-03-01T00:00:00Z until 2026-04-01T00:00:00Z]
```

- **Definition C** (anyone who bought in the month): as above. "Second order" is the next order after their first order in the cohort month; two orders in the cohort month count in month 0.
- **Definition B** (new or reactivated): add `and not exists[event purchase since <cohort start minus 365 days>Z until <cohort start>Z]` to `customers matching`. **(Ran, with a one-week cohort and weekly cutoffs: 385 customers.)**
- **Definition A** for a single month: `and not exists[event purchase until <cohort start>Z]`.
- Count from the **cohort start** (`since`), not from the start of history, or earlier orders make everyone a repeat buyer.
- Add up every row. One query per cohort.
- In testing, the cumulative counts for one month's buyers (8,429 customers, six cutoffs) matched counts worked out independently from each customer's purchase dates **exactly**, at every cutoff.

**Weekly cohorts** (for timing a trigger in days): use a one-week cohort window and cutoffs a whole number of weeks after it ends, for example 1, 2, 4, 8 and 12 weeks. Run the script with `--period week`. **(Ran)**

## F1. Cross-check: repeat buyers and mean time to second order in a window (Ran, `medium`)

```
funnel purchase where .purchase_status = "success" followed by purchase where .purchase_status = "success" since 2026-03-01T00:00:00Z until 2026-08-19T00:00:00Z end
```

- `data.total.counts` = [buyers in the window, buyers with a later second order in the window]. In testing they matched `count customers matching exists[...]` and `count customers matching count[...] >= 2` for the same window exactly (37,958 and 14,578).
- `data.total.times[1]` is the mean time from the first to the second order **in seconds**, although the guide says days (4,509,085, about 52 days). Without `within`, the funnel pairs the first order in the window with the next one, so it is a true first-to-second mean for the window.
- It covers every buyer in the window, not one cohort, and later buyers have less time to come back. Use it as a sanity check.

Same check in one report (Ran):

```
select count customers matching exists[event purchase where .purchase_status = "success" since <start>Z until <end>Z], count customers matching count[event purchase where .purchase_status = "success" since <start>Z until <end>Z] >= 2 by customer.<low_cardinality_property> grouping top 3 with null
```

## Traps (all found in testing)

- **`within N days` in a funnel matches any two orders N days apart**, not the first and second. `count customers matching funnel(purchase followed by purchase since … until … within 30 days)` returned 7,435, half of all 14,578 repeat buyers. In a longer window it returned 8,754 where the true first-to-second count was 6,147.
- A funnel step filtered with `where .timestamp >= <date>` returned 0 with no error.
- `by customer min[event purchase.timestamp ...]` returned no rows with no error: it looks for a property called `timestamp`. `by customer first event purchase timestamp` works, but only for the lifetime first purchase.
- **Shallow history.** If purchases before a date weren't loaded, almost everyone looks like a first-time buyer. In a comparison, a data warehouse whose history began a week before the cohort month called 8,262 customers first-time buyers; in Engagement, with three years of history, only 36 of that month's 8,429 buyers were.
- EQL has no median, percentile or nth-order function. Time to second order comes from cumulative counts at cutoffs.

## Exact days

Exact quartiles would need each customer's purchase dates. This skill doesn't attempt them: it stays aggregate-only, and in testing the approximate quartiles were within a day of the exact ones.

## Avoid

- An item-level purchase event for counting orders.
- Breakdowns by `event purchase timestamp` over all history: rated `high` on a small project and heavier on large ones. Use H1 (a customer count) to find where history starts.
- Breaking down by email, phone, name or any ID property.
