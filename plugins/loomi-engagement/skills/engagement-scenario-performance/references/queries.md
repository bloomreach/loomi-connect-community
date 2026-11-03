# Scenario performance queries

EQL for `execute_analytics_eql`. Replace `<SCENARIO_ID>` with the scenario's 24-character ID, `<STEP>` with a node `id` (a number, unquoted), `<DAYS>` with the period and `<WITHIN>` with the purchase window. Run `estimate_eql_cost` on each shape first.

Queries 1 and 2 were run against a demo project; query 3 was run there grouped by scenario rather than by step. On a project with about 600,000 customers and 7 million events, the per-step cross-tab over 90 days rated `high` (score about 50). Long periods (hundreds of days) rate `very_high`: don't run them.

## 1. Statuses per step

```
select count event campaign where .campaign_id = "<SCENARIO_ID>"
by row event campaign.action_id grouping top 200
by column event campaign.status grouping top 16
in last <DAYS> days
```

Rows are node ids, columns are statuses: `enqueued`, `delivered`, `opened`, `clicked`, `hard_bounced`, `soft_bounced`, `failed`, `unsubscribed` and others (some projects spell them `hard_bounce`, `soft_bounce`, `unsubscribe`; count both). Fold them:

| Number | From |
|---|---|
| sent | max(`enqueued`, `delivered` + bounced) |
| delivered | `delivered` |
| opened, clicked, unsubscribed | the status of the same name |
| bounced | `hard_bounced` + `soft_bounced` + `failed` |

Some projects record only `campaign_name`, not `campaign_id`. If the query returns nothing for a scenario that's known to send, retry with `.campaign_name = "<scenario name>"`.

## 2. Reached and bought after, per step

Every query needs a breakdown to run. Use a one-row breakdown and add the rows up:

```
select
  count customers matching exists[event campaign where .campaign_id = "<SCENARIO_ID>" and .action_id = <STEP> and .status = "delivered" in last <DAYS> days],
  count customers matching funnel(campaign where .campaign_id = "<SCENARIO_ID>" and .action_id = <STEP> and .status = "delivered" followed by purchase in last <DAYS> days within <WITHIN> days)
by customer.country grouping top 1 with null
```

Put up to 3 steps (6 metrics) in one query, and run the batches one after another. Sum each metric across the rows (the top country and "Other").

If the project's purchase event has another name, use it. Check `get_event_schema` if `purchase` returns nothing.

## 3. A/B split assignments

```
select count event campaign where .campaign_id = "<SCENARIO_ID>" and .action_type = "split"
by row event campaign.action_id grouping top 20
by column event campaign.variant grouping top 10
in last <DAYS> days
```

Rows are split node ids, columns are the variant names from the split's `variants`. These are assignments (customers sent down each branch), not results. For conversions per variant and whether the difference is real, use `engagement-experiment-readout`.
