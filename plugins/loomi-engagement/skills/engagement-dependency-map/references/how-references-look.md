# How references look

Where one Engagement definition points at another, as seen live (read-only, November 2026) and in the other skills' testing. Search for IDs and names as plain strings rather than relying on these key names: shapes vary between objects and versions.

## `used_by` on list records

`search_segmentations`, `search_aggregates` and `search_expressions` lists carry `used_by`: a list of `<prefix>_<id>` strings. The ID is everything after the last underscore. Prefixes seen live:

| Prefix | Object | Live-capable? |
|---|---|---|
| `campaign_design_` | scenario | yes |
| `banner_` | weblayer | yes |
| `in_app_message_` | in-app message | yes |
| `segmentation_`, `event_segmentation_` | segmentation, event segmentation | no; follow it |
| `aggregate_`, `running_aggregate_`, `expression_` | derived attribute | no; follow it |
| `prediction_` | prediction (a model trained on that audience) | no; follow it |
| `report_`, `metric_`, `funnel_`, `dashboard_` | analyses | no (reporting breaks) |
| `email_block_`, `snippet_` | reusable template blocks | no, but every template that uses the block is affected |
| `managed_tag_`, `managed_endpoint_`, `contextual_bandit_`, `autosegment_`, `experiment_` | other platform objects | no; mention them |

Customer filter, report, funnel, trend and dashboard lists have no `used_by`. An empty `used_by` means no reference the API tracks: it misses Jinja in templates, exports, imports and API consumers.

## Inside definitions

| Object | Where references sit |
|---|---|
| Segmentation detail | `customer_filter.filters[]` and each `segments[].customer_filter.filters[]`. Conditions are `{"attribute": {...}, "constraint": {...}}`; consent conditions look like `{"attribute": {"type": "consent", "category": "<name>", "mode": "valid"}}`, and event conditions use `steps[]` with an event `name` |
| Expression detail | ordered variable bindings to aggregates, running aggregates or properties (by ID), plus the formula |
| Customer filter detail | `filters[]` and a formula such as `F0&F1` |
| Scenario detail | `nodes[]`: condition nodes' `customer_filter`, `segmentation-fork` nodes' segmentation ID, trigger nodes' event filter (which can name a weblayer ID), action nodes' `consent_category`. Webhook bodies and email designs carry Jinja such as `aggregates['<id>']`, `project_variables.<name>` and `catalogs['<name>']`. Node designs are stripped unless `include_node_designs=true` |
| Email campaign detail | `customer_filter`, `consent_category`; Jinja in the design (`include_design=true`) |
| SMS campaign list | the customer filter and message are in the list records |
| Weblayer and in-app message detail | customer filter and page targeting; Jinja and recommendation or catalog calls in the HTML and JavaScript (never repeat it) |
| Report, funnel, trend, dashboard detail | rows, columns, filters and components, by ID |

Catalogs are covered by `get_catalog_usages`. Recommendation engines are used by ID inside template content.

## What counts as live

Scenarios, email and SMS campaigns, weblayers and in-app messages with status `active` (weblayers: `active`, or `serving` when scheduled). `draft`, `inactive`, `paused` and archived ones aren't live, but deleting something they use breaks them when someone relaunches them. A scenario named in `used_by` but missing from the saved scenario list has an unknown status: load it before calling anything safe.
