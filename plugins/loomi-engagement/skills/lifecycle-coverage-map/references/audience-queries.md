# Audience queries: how many people each flow would get

Every query here returns an **aggregate count** of customers. None of them lists or reads individual customers.

Status labels:
- **Ran:** executed in live testing (November 2026, a demo project).
- **Parsed:** accepted by `estimate_eql_cost` but not executed.
- **Shape:** not tried in this skill; the same shape ran in `winback-opportunity` or `segment-opportunity-finder`.

Replace event, property and category names with the project's own, from `get_event_schema`, `get_customer_property_schema` and `get_consent_settings`. `estimate_eql_cost` doesn't check names, so a typo only shows up as a zero.

## Getting a total

A `select` needs a `by` clause. Break down by a **low-cardinality, non-personal** customer property (country or language, from `get_customer_property_schema`); **never** email, phone, name or any ID property, because `grouping top N` on such a property returns real customers' values, include nulls, and **add up every row**, including `null`, `""` and `other` rows. An empty `rows` list means 0. The script does this when you pass the saved result with `--audience FLOW=<file>`.

```
select count customers by customer.<country_or_language> grouping top 3 with null customers matching <conditions>
```

Put every window **inside** the brackets of `exists[...]`. A trailing `in last N days` after `customers matching ...` doesn't limit the events. When you combine `and` and `or`, use parentheses.

## The queries (one month of entrants unless noted)

| Flow | `customers matching ...` | Status |
|---|---|---|
| Welcome (consent) | `exists[event consent where .action = "accept" and .category = "<email category id>" in last 30 days]` | Parsed (rated `medium` on a demo project of about 600,000 customers) |
| Welcome (no consent events) | `exists[event purchase in last 30 days] and not exists[event purchase until <30 days ago>Z]` (first-time buyers), or a registration event in the last 30 days | Shape |
| Browse abandonment | `exists[event view_item in last 30 days] and not exists[event cart_update where .action = "add" in last 30 days] and not exists[event purchase in last 30 days]` | Shape |
| Cart abandonment | `exists[event cart_update where .action = "add" in last 30 days] and not exists[event purchase in last 30 days]` | Shape |
| Post-purchase | `exists[event purchase in last 30 days]` | Shape |
| Replenishment | `exists[event purchase_item where .category_level_1 = "<replenishable category>" in last 30 days]`; without a category, `exists[event purchase in last 30 days] and count event purchase >= 2` as a rough proxy | Shape |
| Birthday | `customer.<birth date property> has value` (everyone with a date: the script divides by 12) | Shape |
| Win-back | `exists[event purchase in last 120 days] and not exists[event purchase in last 90 days]` (the month's cohort crossing 90 days) | Shape |
| Sunset | `has consent <email category id> and not exists[event campaign where .action_type = "email" and .status = "opened" in last 180 days] and exists[event campaign where .action_type = "email" in last 30 days]` (still mailed, no opens in six months) | Shape. If the 180-day window is `very_high`, skip it: sunset has no revenue figure anyway |

If the user ran `funnel-leak-finder` in the same session, reuse its cart and browse counts instead of these.

## Cost

- Customer counts with windowed `exists` were rated `medium` on a demo project and are usually `high` on large production projects. Tell the user before the first query that sizing takes about 6–8 aggregate queries, and ask once.
- Never run a `very_high` query. Narrow the window or skip that flow's figure and say so.
- One query at a time, about 4 seconds apart. On HTTP 429, wait 6–10 seconds and retry once.

## Revenue at stake

```
monthly audience   = count ÷ the flow's audience_months (12 for birthday)
monthly value      = monthly audience × reachable share × conversion rate × AOV
at stake           = monthly value          (missing, draft or stopped)
                   = monthly value × weak_share_at_stake   (weak)
                   = 0                      (live)
```

- **Reachable share:** the email-reachable share from `contactability-audit` if the user has it, otherwise `default_reachable_share` from `rules.json`, labelled as an assumption.
- **Conversion rates:** from `rules.json`, `conversion_rate` per flow: conservative planning assumptions, not benchmarks. Use the user's own flow results where they have them.
- **AOV:** the 30-day AOV query (pattern V in `winback-opportunity`), or the user's figure.
- Sunset has **no revenue figure**: its value is deliverability for every other flow.
- Don't add flows together as if they were independent: one customer can be in several. Present the total as "up to".
