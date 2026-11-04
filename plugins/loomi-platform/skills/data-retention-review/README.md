# Data retention review

Compares a Bloomreach Engagement project's event retention rules with what its analytics and automations need. It finds segments, aggregates, reports, funnels and other definitions whose lookback windows reach further back than the events they read are kept, windows this repository's skills rely on (such as win-back's) that retention cuts short, events kept far longer than anything reads them, and customer properties that look personal, which event retention never removes. Not legal advice.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_data_retention_rules`*, `get_event_schema`, `get_customer_property_schema`, `search_segmentations`, `search_customer_filters`, `search_event_segmentations`, `search_aggregates`, `search_running_aggregates`, `search_expressions`, `search_predictions`, `search_reports`, `search_funnels`, `search_trends` (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | Python 3 for `scripts/data_retention_review.py` (standard library only) |
| **Tested with** | Claude Code: retention rules, customer property schema and aggregate detail shapes checked live on a demo project; the review itself run on synthetic fixtures |
| **Maintainer** | @bloomreach |

## Example prompts

- "Do our data retention rules break any segments or reports?"
- "How long do we keep events, and do we keep anything longer than we need?"
- "Which personal data do we hold on customer profiles?"

See [examples/illustrative-review.md](examples/illustrative-review.md) for illustrative output.

## Notes and limitations

- Read-only, and not legal advice: retention periods are a decision for the data protection lead or legal counsel.
- Data Manager retention covers events only. Customer properties stay on the profile until it's anonymised or deleted.
- Personal data is spotted by property name (`personal_words` in `references/rules.json`), so a personal value in a generically named property isn't caught.
- It reads only the definitions it fetches (up to `max_details`); scenario waits, exports and integrations can need history too.
- It never reads customer profiles or property values, and doesn't use `get_customer_attribute_values` (a one-customer evaluation tool) or `get_datahub_system_configuration` (Data Hub's built-in item attributes, not retention).
