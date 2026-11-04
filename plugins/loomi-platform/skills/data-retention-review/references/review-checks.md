# Data retention review checks

What each check in `scripts/data_retention_review.py` looks for and what to consider changing. Thresholds, word lists and skill windows are keys in `rules.json`; this file names the key, never its value.

## What the tools hold

- **`get_data_retention_rules`** (via `search_tools` and `call_tool`): the Data Manager **event** retention for a project: `default_retention_enabled` with a `default_duration` (`{count, units}`), and `event_overrides[]` (`event_type`, `retention_enabled`, `duration`). Per the tool's description, an override replaces the default for its event type, so an override with `retention_enabled: false` keeps that event forever even when the default expires others. There is no retention setting for customer properties.
- **`get_datahub_system_configuration`** is not a retention setting: it returns the built-in item attributes (title, price, brand …) Data Hub allows for an item type. This skill doesn't use it.
- **`get_customer_property_schema`**: property names, types and `used` (whether any customer has a value). It also has an `example_values` field: never read or repeat it.
- **`get_customer_attribute_values`** evaluates aggregates or expressions for one customer. It isn't a counting tool, so this skill doesn't use it.
- **`get_event_schema`**: event types and their property names under `events[].properties.<group>.properties[]`.

## Where windows come from

| Shape | Read as |
|---|---|
| `date_filter` or report-wide `event_filters.date` with `enabled: false` | **All time** (lifetime), except a report member's own `date_filter`, which then follows the report-wide date |
| `enabled: true`, `absolute: false` | Rolling: `duration` (plus `offset` if it's a duration) |
| `enabled: true`, `absolute: true` | From `from_date` (Unix seconds) to the review date |
| Event filter on `{"type": "timestamp"}` with `operator` "in the last" | Rolling window of `amount` `units` |
| Event filter on `{"type": "timestamp"}` with `operator` "more than" and `tense` "ago" | Needs events **older** than `amount` `units`: retention must be longer |

A window applies to the event types named in the same object (`event.type`, funnel `steps[].type`, `event_type`), else to the nearest enclosing object's events, else to every event the definition names. A funnel's `duration_filter` is a conversion window, not a lookback, and is ignored. Units convert with `unit_days`.

## Checks

| Check | Priority | When | Change to consider |
|---|---|---|---|
| Window never satisfiable | High (kind in `feeds_live_kinds`) / Medium | A "more than N ago" condition on an event deleted after N or less | Keep the event longer, or change the condition |
| Window longer than retention | High (`feeds_live_kinds`) / Medium (reports, funnels, trends) | A rolling or absolute window reaches further back than the event is kept | Shorten the window, or keep the event longer |
| Lifetime window on expiring events | Medium (`feeds_live_kinds`) / Low | An all-time window reads an event that expires | Accept and relabel, or keep the event longer |
| Skill window longer than retention | Medium | A `skill_needs` entry reads further back than the event is kept (skipped when the event schema shows the project doesn't track the event) | Expect that skill to under-count, or keep the event longer |
| Personal data kept longer than used | Medium | An event kept forever, or more than `overkeep_factor` × its longest read (at least `min_keep_days`), has properties matching high or medium `personal_words` | Set a retention rule close to real use |
| Kept forever, nothing reads it | Low | No retention and no window found reads it | Consider a rule, after checking scenarios and exports |
| Kept forever, read briefly | Low | No retention, and every window found is limited | Consider a rule a little longer than the longest window |
| Kept much longer than read | Low | Finite retention above `overkeep_factor` × the longest read | Consider shortening |
| Rule for an unknown event | Low | A rule names an event type the schema doesn't list | Remove it or fix the name |
| Personal customer property without retention | High / Medium / Low by `personal_words` level | A customer property name matches a personal word (not overridden by `not_personal_words`, unless high) | Confirm it's needed; drop what isn't; agree an anonymisation or deletion routine |
| Personal property never filled | Low | Personal-looking and `used: false` | Remove the definition |

Name matching is a heuristic: it finds `birth_date` and `wifeBirthdate`, and misses a property called `notes` that holds health details. Say so in the report.

## Not covered

Scenario waits and conditions, exports, imports, integrations and API consumers can need history too; the review only knows the definitions passed to it. Event retention doesn't remove customer properties, consents or profiles; Engagement's anonymisation and deletion features do. This is a data-management review, not legal advice.
