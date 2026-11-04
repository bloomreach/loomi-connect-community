# Journey health queries

EQL for `execute_analytics_eql`. Run `estimate_eql_cost` once per query shape first. Replace `<CHANNELS>` with the message `action_type` values from query 1, `<START>`, `<MID>` and `<END>` with ISO dates ending in `Z`, `<SCENARIO_ID>` with a scenario's 24-character hex ID and `<DAYS>` with a number. Names inside quotes (channels, events, properties, values) come from the project: escape backslashes (`\` → `\\`) and double quotes (`"` → `\"`) first.

All of these were run against a sandbox project with about 75,000 customers and 23 million events. Each `campaign` event query rated `high` (score 38–46); customer counts rated `medium`. Wait about 5 seconds between queries. On HTTP 429, wait for `Retry-After` (5–10 seconds if it isn't set) and retry.

## 1. Which `action_type` values are messages

```
select count event campaign by row event campaign.action_type grouping top 30 by column event campaign.status grouping top 20 in last <DAYS> days
```

Keep the channels that send a message: `email`, `sms`, `mms`, `mobile notification`, `browser notification` (with spaces), `whatsapp`, `webhook` and the project's own channel names. Email records `enqueued`, then `delivered` or `hard_bounced` / `soft_bounced`; SMS and push record `sent` with no `delivered`. Leave out scenario plumbing, which also records `campaign` events: `split`, `set property`, `set property raw`, `add event raw`, and weblayer events such as `banner` (status `serve`). Values are case sensitive, so `SMS` and `sms` are different channels: keep both if both send.

## 2. Every flow and step by status (one query per period)

```
select count event campaign where .action_type is in [<CHANNELS>] by row event campaign.campaign_id grouping top 100 by row event campaign.action_id grouping top 100 by column event campaign.status grouping top 20 since <MID> until <END>
```

Run it again with `since <START> until <MID>` for the previous period. Two `by row` clauses give one row per scenario and step (`campaign_id` is the scenario ID, `action_id` the node `id`). `is in` needs at least two values; with one channel, use `.action_type = "email"`.

- Cross-tabs list rows and columns that the `where` filter excludes, with zero counts (steps of other scenarios, statuses such as `serve`). Drop them.
- If a single-breakdown result has a large `other` row, raise `grouping top`.
- Rows for IDs that aren't in the active scenario list are standalone campaigns or inactive scenarios.

## 3. Why a step didn't deliver

```
select count event campaign where .campaign_id = "<SCENARIO_ID>" and .status is in ["suppressed", "aborted", "enqueue_failed"] by row event campaign.message grouping top 20 with null by column event campaign.status grouping top 10 since <START> until <END>
```

Never add bounce or failure statuses (`hard_bounced`, `soft_bounced`, `failed`) to this query: bounce texts often quote the recipient's address. Hand bounces to `deliverability-trend`, which breaks them down by error code and mailbox provider. `message` (and `error`) hold the reason, for example "This customer has not given consent for this category", a template `abort` text such as "No qualifying products available", or "Rendering failure … Timeout … exceeded". For delivered SMS, `message` holds the message text, which is why the status filter matters. Summarise reasons; don't paste text that contains personal data. Tested project-wide; adding the `.campaign_id` filter narrows it to one flow.

## 4. When it changed (one flow)

```
select count event campaign where .campaign_id = "<SCENARIO_ID>" and .status = "delivered" by row event campaign timestamp format year month day by column event campaign.action_id grouping top 20 in last <DAYS> days
```

Rows are days (Unix seconds at midnight in the project's time zone), columns are steps. A step that falls to near zero after the first few days, while the trigger keeps firing, usually means a condition lets each customer through only once.

## 5. Finding the condition that lets nobody through

Size the path from the trigger, one condition at a time, and stop at the first zero. Every query needs a breakdown; use a one-row breakdown and add up the rows (including `other` and the empty value).

| Condition | Query |
|---|---|
| Event trigger | `select count event <EVENT> by event <EVENT>.<PROPERTY> grouping top 5 with null in last 14 days` (with the trigger's own property filter in `where`) |
| Customer property has a value | `select count customers by customer.<PROPERTY> grouping top 3 with null` (one row of "empty" means nobody has it) |
| Did an event (with filters) in the last N days | `select count customers by customer.country grouping top 1 with null customers matching exists[event <EVENT> where .<PROP> = "<VALUE>" in last <N> days]` |
| Didn't do an event | add `and not exists[event <EVENT> in last <N> days]` |
| Consent | add `and (has consent <CATEGORY> or has consent <CATEGORY>)` |

Put the window inside the brackets: a trailing `in last N days` after `customers matching` doesn't limit the events. Conditions that use segmentations, aggregates, expressions or Jinja can't be translated reliably: say "not sized" and suggest checking the condition in the Engagement UI.
