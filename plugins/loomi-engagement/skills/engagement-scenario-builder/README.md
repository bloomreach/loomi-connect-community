# Engagement scenario builder

Builds a Bloomreach Engagement scenario (automation flow) from a plain-English description, or changes an existing draft. It turns "when someone abandons a cart, wait 4 hours, and if they still haven't bought, send the reminder" into real triggers, waits, conditions and connections, checks the result, shows it for approval, and saves it as a **draft**. Switching it on stays in the Engagement UI.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: creates a draft scenario, or updates a draft or stopped one (`update_scenario`, or `update_scenario_node` for one node), after explicit confirmation |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_event_schema`, `get_customer_property_schema`, `search_segmentations`, `search_predictions`, `search_aggregates`, `search_expressions`, `get_consent_settings`*, `search_api_triggers`, `search_scenarios`, `search_scenario_nodes`*, `create_scenario`, `update_scenario`*, `update_scenario_node`*, `estimate_eql_cost`, `execute_analytics_eql`, `get_guide` (* found with `search_tools` and run with `call_tool` if not listed) |
| **Tested with** | Claude Code: step shapes, output numbering and the check script were verified against scenarios saved in a demo project, read-only. The write path follows the Loomi Connect guide `scenario-write-best-practices`; a live create was not run for this release. Not yet tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Build an abandoned cart flow: wait 4 hours, then email anyone who still hasn't bought."
- "Set up a weekly win-back for people who haven't bought in 90 days, at most 1,000 a week."
- "Copy our welcome series into a new draft and add a 2-day wait before the second email."
- "In the draft 'Spring launch', change the wait to 3 days."

See [examples/build-and-change.md](examples/build-and-change.md) for illustrative output.

## Notes and limitations

- Running scenarios are never edited in place: changes become a new draft copy.
- It doesn't write email, SMS or push content. It reuses existing messages (copied with their design) or leaves a note where the message goes.
- Some step types (segmentation forks, personalised splits, dynamic and silent-hours waits, typed attribute values) aren't built from scratch: their saved shape isn't verified, so they're copied from an existing scenario instead.
- [assets/templates.json](assets/templates.json) holds starting outlines (welcome series, abandoned cart, win-back) in `create_scenario` format. Apps can read the same file.
- [scripts/check_scenario.py](scripts/check_scenario.py) (standard library, no network) checks a payload before it's written: triggers, ids, output numbers, conditions, schedules, splits, webhooks, and, for updates, lost designs and status.
