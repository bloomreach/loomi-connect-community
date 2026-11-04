# Reading analysis definitions

How to turn the fields returned by the `search_*` tools (called with an ID) into plain English. Field names below were checked against live responses in October 2026; where a field wasn't seen in testing, it's marked "per the tool description".

All responses from these tools are wrapped as `{"result": {"success": ..., "data": {...}}}`. `calculate_report` is **not** wrapped: it returns `{"success": ..., "as_dict": ..., "definition": ...}`.

## Date filters (used everywhere)

A date filter looks like:

```json
{"enabled": true, "absolute": false, "duration": {"count": 30, "units": "days"},
 "from_date": null, "to_date": null, "offset": null}
```

| Fields | Means |
|---|---|
| `enabled: false` | **No date limit: all time.** The `duration` is still filled in (often the UI default of 30 days) but is ignored. Easy to misread. |
| `enabled: true`, `absolute: false` | Rolling: the last `count` `units` up to now (or up to `execution_time`). `offset` shifts the window back. |
| `enabled: true`, `absolute: true` | Fixed: from `from_date` to `to_date` (Unix seconds). Convert both to dates and compare `to_date` with today. |

Always state the window as actual dates.

## Filters and conditions

An event filter is a list of conditions, each:

```json
{"attribute": {"type": "property", "property": "action"},
 "constraint": {"type": "string", "operator": "equals",
                "operands": [{"type": "constant", "value": "clarity_respond"}]}}
```

Read it as "`action` equals `clarity_respond`". Conditions in one list are ANDed.

A customer filter is `{"filters": [...], "formula": "F0&F1"}`. `F0`, `F1`, ... are the filters by position; `&` is AND, `|` is OR, `!` is NOT. An empty `filters` list with an empty `formula` means **all customers**.

Attribute types you'll meet: `property` (event or customer property), `timestamp`, `expression`, `aggregate`, `prediction`, `segmentation` (each of the last four has an `id` to look up).

Operators to translate carefully: `equal to` / `equals`, `in` / `is in`, `has value`, `has no value`, `contains`, `matches regex` (it must match the whole value, so a pattern such as `gmail` without `.*` around it matches nothing; flag that as a likely mistake), numeric `greater than` and so on. A `not` variant or a `!` in the formula excludes.

## Reports (`search_reports` with `report_id`)

The definition is under `server`:

| Field | Meaning |
|---|---|
| `metrics[]` | Each column of numbers. `name` is the label. For `type: "embedded_metric"`, `members[]` are the parts (`V0`, `V1`, ...) and `formula` combines them (e.g. `V0/V1*100`). `format` is display rounding. |
| `metrics[].members[]` | `type: "event"` with `event.type` (the event name) and `event.filter` (conditions); `aggregation` (`count`, `sum`, `average`, `unique`, ...); `attribute` (the property summed or averaged); `occurrence_per_customer` (`all` = every event; `first`/`last` = one per customer); its own `date_filter` and `customer_filter`. |
| `event_filters.date` | The report-wide date window. A member's own `date_filter` with `enabled: false` means it follows this one. |
| `event_filters.attributes[]` | Report-wide event filters, per event type. |
| `customer_filter` | Who's included. |
| `rows[]`, `columns[]` | Breakdowns. `attribute.type: "timestamp"` with `format` such as `year month day` is a time series. `grouping` (`none`, ranges, top N) and `hide_null` change what appears. |
| `attributes_use_global_events` | Breakdown attributes come from the report-wide events. |
| `parametrized`, `parameters`, `parameter_values` | Runtime parameters; see `calculate_report`. |

Chart settings and UI modifiers are not returned, so you can't tell whether the UI shows a chart, a table or a percentage view.

### `calculate_report` results

- `as_dict` maps each row key to a list of numbers, **one per metric in `server.metrics[]` order**.
- For a timestamp breakdown, keys are bucket starts as Unix seconds (strings), aligned to midnight in the project's time zone.
- In testing, buckets with zero were returned even with `hide_null: true`.
- With columns as well as rows the shape is nested; read it carefully and say if you're unsure.
- With `parameter_values`, the result uses a different, hierarchical shape (the same family as `execute_analytics_eql`).

## Funnels (`search_funnels` with `funnel_id`)

| Field | Meaning |
|---|---|
| `funnel_steps.steps[]` | Ordered steps. `type` is the event name; `filter` is the step's conditions; `name` is the label. Repeated identical steps (purchase, purchase, purchase) count repeat behaviour: "made a 2nd, 3rd ... purchase". |
| `funnel_steps.date_filter` | When the first step must happen. Check `enabled`. |
| `funnel_steps.duration_filter` | The conversion window between first and last step. `enabled: false` means **no limit**. |
| `funnel_steps.independent_if_reused` | Whether a repeated event can satisfy more than one step. |
| `customer_filter` | Who's included. |
| `drill_down` | Breakdown of the funnel (`type: "none"` if none). |
| `metric` | Optional metric per step (often `null`). |

There's no top-level date filter on a funnel.

## Trends (`search_trends` with `trend_id`)

Per the tool description (no trend was available to test): `event_types[]` are the series with their filters, `date_filter` the window, `group_by` the time granularity, `unique_per_customer` whether it counts customers rather than events, and `customer_filter` who's included.

## Segmentations (`search_segmentations` with `segmentation_id`)

`customer_filter` is the global pre-filter: customers who don't match are in **no** segment. `segments[]` each have a `name` and a `customer_filter`. A customer goes into the **first** segment they match, in order, so later segments implicitly exclude earlier ones. `metrics` are per-segment numbers shown in the UI. Sizes aren't returned: count them with EQL if needed.

The list response's `used_by` shows where it's used: `dashboard_`, `report_`, `funnel_`, `metric_`, `segmentation_`, `campaign_design_<scenarioId>` (a scenario).

## Event segmentations (`search_event_segmentations` with `event_segmentation_id`)

Per the tool description (none available to test): `segments[]` each have a name and event-attribute conditions, bucketing customers by behaviour such as their most-purchased category.

## Dashboards (`search_dashboards` with `dashboard_id`)

| Field | Meaning |
|---|---|
| `components[].type` | `report`, `metric` (a KPI tile), `text`, `html`, and per the tool description other embedded analyses and images. |
| `components[].id` | The embedded analysis ID (look it up with the matching `search_*` tool). `metric` IDs have no read tool. |
| `components[].position` | `x`, `y` (grid units, 12 columns wide), `width`, `height`. **Sort by `y` then `x`**; the list isn't in display order. |
| `components[].display` | For reports: `chart` or `table`. |
| `components[].date_filter`, `comparison`, `goal` | Per-tile overrides. `null` means the tile uses the analysis's own window. |
| `text` | Headings or notes. A single space is a layout spacer. |
| `html` | Free HTML (often a reference table). Summarise; don't paste. `evaluate: true` means it contains Jinja. |
| `home`, `shared` | Whether it's the project's home dashboard, and whether it's shared with the team. |
