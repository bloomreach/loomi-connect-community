# Engagement dependency map

Answers "what uses this, and what breaks if I change or delete it?" for Bloomreach Engagement definitions: aggregates, running aggregates, expressions, segmentations, customer filters, predictions, catalogs, recommendation engines, consent categories and project variables. For one item or a list of candidates (for example the delete and archive list from [engagement-asset-cleanup](../engagement-asset-cleanup/)), it finds references in scenarios, email and SMS campaigns, weblayers, in-app messages, segmentations, aggregates, expressions, reports, funnels, trends and dashboards, follows indirect chains (an expression used by a segment used by a scenario), and returns each item's dependants, a verdict (blocked, check first, or no dependants found) and a safe deletion order: leaves first, anything feeding a live scenario or campaign blocked. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_segmentations`, `search_event_segmentations`, `search_customer_filters`, `search_aggregates`, `search_running_aggregates`, `search_expressions`, `search_predictions`, `search_scenarios`, `search_scenario_nodes`*, `search_email_campaigns`, `search_sms_campaigns`, `search_banners`, `search_in_app_messages`, `search_catalogs`, `get_catalog_usages`, `search_recommendations`, `list_project_variables`, `search_reports`, `search_funnels`, `search_trends`, `search_dashboards` (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | None. Python 3 is optional, for the bundled script (standard library only) |
| **Tested with** | Claude Code, read-only and metadata only, on a demo project: `search_segmentations` (list and one detail), `search_expressions` and `search_aggregates` (lists), `search_customer_filters` (list) and `search_scenarios` (list and one detail), to confirm `used_by` prefixes and where references sit. The script was tested on synthetic responses. Email, SMS, weblayer, in-app message, prediction, recommendation, catalog and analysis details were not fetched live. Not run end to end, and not tested in an OpenAI client. |
| **Maintainer** | Bloomreach |

## Example prompts

- "What uses the 'High spenders' segment?"
- "Is it safe to delete the 'Total spend 365d' aggregate?"
- "Which campaigns use the brand_name project variable?"
- "Here's the cleanup list. In what order can we delete these without breaking anything?"

See [examples/illustrative-dependency-map.md](examples/illustrative-dependency-map.md) for an example output. Its names and numbers are illustrative.

## How it works

1. Lists every object kind once, keeping names, statuses and `used_by` lists (segmentations, aggregates and expressions carry them).
2. Fetches the definitions that can hold references: each target, everything in a `used_by` chain, scenarios, campaigns, weblayers, in-app messages and customer filters, with template designs only when a target is used from Jinja (project variables, catalogs, recommendations). See [references/how-references-look.md](references/how-references-look.md).
3. [scripts/engagement_dependency_map.py](scripts/engagement_dependency_map.py) builds the graph from the saved responses (by `used_by`, ID, consent category name and Jinja pattern), walks it breadth-first so cycles can't loop, and returns dependants, verdicts and a deletion order. Its rules are in [references/rules.json](references/rules.json).
4. Reports what blocks each item and what wasn't checked.

## Notes and limitations

- **References outside definitions aren't visible.** Exports, imports, integrations, API consumers and people reading a report in the UI don't show up, so "no dependants found" means "nothing checked uses it", not "safe for certain".
- Project variables, catalogs and recommendation engines are used from template code, which needs designs fetched (`include_node_designs`, `include_design`). On large projects the skill checks the likeliest scenarios and campaigns and says how many it checked.
- A match on a target's name alone is labelled "name (verify)", because two objects can share a name.
- `search_email_campaigns`, `search_sms_campaigns`, `search_predictions`, `search_recommendations` and `search_in_app_messages` can return HTTP 403; those kinds are reported as not checked.
- Lists include editor names, and details include message and weblayer content; the report never repeats them.
