# EQL patterns for a revenue change

Tested patterns for each step. Replace `purchase`, `total_price`, `purchase_id`, `purchase_status`, `"success"` and the dimension names with the project's own, from `get_event_schema`. Replace `<P0>`/`<P1>` (previous period start and end) and `<C0>`/`<C1>` (current period start and end) with ISO dates ending in `Z`, for example `2026-07-01T00:00:00Z`. `until` is exclusive. Before putting a status or segment value inside quotes, escape backslashes (`\` → `\\`) and double quotes (`"` → `\"`).

Status labels: **Ran** = executed in read-only testing on a sandbox project (about 75,000 customers, 23 million events), November 2026. Costs are from that project; on large projects expect the same level or one higher.

## K. Revenue, orders and buyers for one period (Ran, high)

```
select sum event purchase.total_price, count event purchase, count first event purchase by event purchase.purchase_status grouping top 10 with null since <C0> until <C1>
```

- One row per status. Use the completed-status row; add up the others to say what was left out.
- `count first event purchase` = unique customers with at least one purchase in that row's status.
- The value property can be typed `string` in the schema and still sum.
- Run it once per period. Don't use a month breakdown (`by event purchase timestamp format year month`) for the two periods instead: its buckets follow the project's time zone while `since … until …Z` is UTC, so the edges can disagree.

## C. Buyers, cheaper cross-check (Ran, medium)

```
select count customers by customer.<low_cardinality_property> grouping top 3 with null customers matching exists[event purchase where .purchase_status = "success" since <C0> until <C1>]
```

Add up every row, including `null`. Must equal pattern K's buyers.

## U. Duplicate order IDs (Ran, high)

```
select count event purchase by event purchase.purchase_id grouping top 3 since <P0> until <C1>
```

- `grouping top 3` keeps the three order IDs with the most events. If each has 1, no order ID repeats in the window. Rows come back sorted by ID, not by count: read all three. Report counts only (how many IDs repeat, how many extra events), never the IDs; `revenue_split.py --order-ids` does this.
- `other` + the three rows = all purchase events in the window.
- In testing, a clean two-month window had 1 event per ID, while a three-year window had two IDs with over 1,100 events each, worth about $720,000 of "revenue". Always check the window you're comparing.
- EQL has no distinct count of a property (`count distinct` doesn't parse). If IDs repeat, filter to the completed status and recheck; if they still repeat, report the surplus rather than trying to de-duplicate.

## D. Daily shape, data horizon and project time zone (Ran, high)

```
select sum event purchase.total_price where .purchase_status = "success", count event purchase where .purchase_status = "success" by event purchase timestamp grouping top 62 format year month day since <P0> until <C1>
```

- One row per day with data. Header values are Unix seconds of each day's **start in the project's time zone**: `1782864000` = `2026-07-01T00:00:00Z` means the project is on UTC; a start at `22:00Z` means UTC+2. Daylight saving moves it.
- Days with no events are missing, not zero. Count the rows: fewer than the days in the window means gaps.
- `grouping top N` with N at least the number of days.
- Use the same query on the item-level event (with `format year month` and a long window) to see from when that event exists.

## N. New buyers in a period (Ran, high)

```
select sum event purchase.total_price, count event purchase, count first event purchase by event purchase.purchase_status grouping top 10 with null customers matching not exists[event purchase until <C0>] since <C0> until <C1>
```

- `customers matching` before `since … until …`.
- Gives new buyers' revenue, orders and count. Returning = pattern K minus this.
- `not exists[event purchase until <C0>]` looks at the whole history the project holds: if history starts shortly before the period, almost everyone is "new".

## R. Retained, reactivated and new buyers in one query (Ran, medium)

```
select count customers matching (exists[event purchase where .purchase_status = "success" since <C0> until <C1>] and exists[event purchase where .purchase_status = "success" since <P0> until <P1>]), count customers matching (exists[event purchase where .purchase_status = "success" since <C0> until <C1>] and not exists[event purchase where .purchase_status = "success" since <P0> until <P1>] and exists[event purchase where .purchase_status = "success" until <P0>]), count customers matching (exists[event purchase where .purchase_status = "success" since <C0> until <C1>] and not exists[event purchase where .purchase_status = "success" until <C0>]) by customer.<low_cardinality_property> grouping top 3 with null
```

- Three metrics: **retained** (bought in the previous period too), **reactivated** (bought before, but not in the previous period), **new** (first purchase ever). Add up each column across all rows.
- The three must add up to the period's buyers from pattern K: a free cross-check.
- Run it for the previous period too, with that period's own previous period (for June vs July: May for June), to compare like with like.

## B. Revenue by a dimension (Ran, high)

```
select sum event purchase.total_price where .purchase_status = "success", count event purchase where .purchase_status = "success", count first event purchase where .purchase_status = "success" by event purchase.<dimension> grouping top 10 with null since <C0> until <C1>
```

- Once per period, same dimension. Revenue and orders across rows add up to pattern K; **unique buyers don't** (one customer can sit in several rows).
- Always `with null`, and report the `null` row as its own segment ("no campaign attributed"). If it's most of revenue, the dimension only describes part of the change: say so.
- `grouping top N` ranks by the underlying event count, not by the filtered sum. Add up `other` too.

## F. Buyers by number of orders in the period (Ran, medium)

```
select count customers by customer count[event purchase where .purchase_status = "success" since <C0> until <C1>] grouping top 10 customers matching exists[event purchase where .purchase_status = "success" since <C0> until <C1>]
```

- One row per order count (1, 2, 3 …). Rows add up to the buyers, and rows × order count add up to the orders: two more cross-checks.
- Shows whether "more orders per buyer" means many people ordering twice or a few ordering many times.

## Syntax traps

- `since … until …` with `Z`. `until` is exclusive. `from … to …` doesn't parse.
- `where` comes before the window inside `exists[...]`, and joins conditions with `and` only.
- A `select` needs a `by`. For one total, break down by a low-cardinality property `with null` and add up every row.
- `customers matching` goes after `by` and before a trailing window.
- `estimate_eql_cost` doesn't check names, and lists "lifetime date range" even when every window is inside brackets.
- Zero matches can come back as an empty `rows` list, a `0`, or a row with `null`.
