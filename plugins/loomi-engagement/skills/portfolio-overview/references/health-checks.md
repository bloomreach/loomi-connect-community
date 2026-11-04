# Portfolio health checks

How [scripts/portfolio_health.py](../scripts/portfolio_health.py) scores each project, so the same result can be worked out by hand. Every number named here is a key in [rules.json](rules.json); change it there.

## The score

Each project starts at 100. Each flag takes off its `deduct` points from `flags` in rules.json, and the score stops at 0. The band is **green** at `score_green` or above, **amber** at `score_amber` or above, and **red** below that. A project whose overview couldn't be read has no score (band "unknown").

The score is a triage aid, not a grade. It only uses what the overview returns (plus deeper mode, if run), so a green project can still have problems that only a per-project skill finds.

## Comparable projects and the median

Outlier flags compare a project with the **median of comparable projects**: those that aren't test-like and have both customers and events. With fewer than `min_projects_for_median` comparable projects there's no median and no outlier flag. Test-like projects are never flagged as outliers.

Events per customer is all-time stored events divided by total customers. It reflects tracking depth and data retention as much as engagement, so treat it as a pointer.

## Flags

| Code | Raised when | Priority |
|---|---|---|
| `overview_unavailable` | The project's `overview_error` is set or it has no overview. Not scored. | medium |
| `events_unknown` | The overview has no readable `events` count. Event checks are skipped; it takes nothing off the score. | medium |
| `no_events` | `events` is 0. Other overview checks are skipped. | high |
| `small_customer_base` | Has events, but `total_customers` is below `min_customers`. | medium |
| `few_event_types` | Fewer than `min_event_types` event types in `event_types_overview`. | medium |
| `no_campaign_events` | `event_types_overview` has no `campaign` event (or a count of 0): no email, SMS, push or webhook send has ever been recorded. | medium |
| `outlier_low` | Customers, or events per customer, below `outlier_low_ratio` × the median. One flag, listing which. | medium |
| `outlier_high` | Events per customer above `outlier_high_ratio` × the median: worth checking for duplicate or bot tracking. | low |
| `shrinking_customers` | With a baseline: customers fell by more than `shrink_ratio` of the baseline count. | medium |
| `fewer_events` | With a baseline: stored events fell at all (data retention or deletion). | low |
| `no_recent_events` | Deeper mode: the 7-day event count query returned no rows. | high |
| `busy_types_silent` | Deeper mode: one of the project's `busy_event_types` busiest non-system event types (all-time, leaving out `system_event_types`) has no events in the last 7 days. Not judged when the query returned `recent_top_n` rows, because missing types may just be cut off. | medium |
| `no_live_scenarios` | Deeper mode: `search_scenarios` with `status="active"` returned no live (unarchived, active) scenarios. | high |
| `test_or_sandbox` | `category` is in `sandbox_categories`, or a whole word of the name or URL slug is in `test_name_words`, or the name contains "copy of". Takes nothing off. | low |

## Hand-offs

Each flag's `handoff` in `flags` in rules.json names the skill that looks into it. That's the only place they're defined.

## Deeper mode

Per project, in this order and one call at a time: `estimate_eql_cost`, then `execute_analytics_eql` for `select count any event by any event type grouping top <recent_top_n> in last 7 days` (only if rated low or medium), then `search_scenarios` with `status="active"` and `limit` set to `max_scenarios_page`. That's `deep_calls_per_project` calls. Projects are suggested lowest score first, comparable projects before test-like ones, up to `max_deep_projects`. Projects with no events at all are never suggested: there's nothing more to learn from them.

Event types with no events in the window don't appear in the EQL rows. A full page of active scenarios (`max_scenarios_page`) is reported as "that many or more".
