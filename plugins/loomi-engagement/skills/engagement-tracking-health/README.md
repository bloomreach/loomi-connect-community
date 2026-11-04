# Engagement tracking health

Audits an Engagement project's tracking and data quality. It finds event types that stopped, dropped or spiked; junk or unexpected event types; properties that are often empty or hold drifting values; and schema oddities such as type conflicts and misspelt duplicates. It uses aggregate EQL counts only, and it never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_event_schema`, `get_customer_property_schema`, `get_customer_schema`, `estimate_eql_cost`, `execute_analytics_eql`, optionally `get_project_overview`, `search_trends`, `search_reports` |
| **Tested with** | Claude Code (manual run of the method, the EQL patterns and the script against a live sandbox project, plus a schema-only check of a production project). Version 0.1.6: the purchase history and duplicate order queries were run on a sandbox with 23 million events; both totals matched an earlier independent count (485,313 purchases) |
| **Maintainer** | Bloomreach |

## Example prompts

- "Is our Engagement tracking working properly?"
- "Have any events stopped coming in?"
- "Run a data quality audit on the customer properties."
- "Why are there so many weird event types in our schema?"

See [examples/illustrative-audit.md](examples/illustrative-audit.md) for an example output. Its names and numbers are illustrative.

## How it works

- **Volumes:** one cheap EQL query per window (last 7 days, the previous 7 days via `execution_time`, and the last 90 days) counts events by event type. Comparing the results with the schema shows types that went silent.
- **Fill rates:** a `with null` breakdown on a few chosen properties. It counts empty strings as missing as well as nulls.
- **Schema checks:** [scripts/tracking_checks.py](scripts/tracking_checks.py) flags junk or look-alike event type names, conflicting property types and likely misspellings. It uses only the Python standard library and makes no network calls.

[references/eql-patterns.md](references/eql-patterns.md) has every tested query, its cost rating and the syntax traps found.

## Notes and limitations

- EQL is rate-limited to about one query every 3 seconds per project, so a full audit takes a minute or two.
- The cost estimator rates event-property breakdowns "high" whatever the date range, and customer-property scans are "high" on large projects. The skill asks before running those.
- `used: true` in the schema means a value has *ever* been seen, not that it's still being filled.
- There are no statistical tests. On low-volume events, week-on-week swings are noise, and the skill labels them "low volume".
