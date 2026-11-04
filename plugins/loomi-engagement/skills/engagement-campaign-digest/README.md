# Engagement campaign digest

Builds a weekly (or any period) digest of email and SMS campaign performance in a Bloomreach Engagement project: sends, delivery, opens, clicks, bounces, unsubscribes and revenue where available. It compares the period with the one before, names the best and worst campaigns, and flags issues. It uses aggregate data only and never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_campaign_calendar`, `search_email_campaigns`, `search_sms_campaigns`, `search_scenarios`, `search_reports`, `calculate_report`, `get_event_schema`, `estimate_eql_cost`, `execute_analytics_eql` |
| **Tested with** | Claude Code: each step run by hand against a live sandbox and a production project. Those projects had very few email or SMS sends, so the full digest has not yet been checked on a high-volume project. Version 0.1.7: the report-level filter (patterns B, C) and unique counts (pattern E) were run against a sandbox with about 37,000 email deliveries a month; pattern E's unique counts were cross-checked against a month of opens and clicks. |
| **Maintainer** | Bloomreach |

## Example prompts

- "How did our emails do last week?"
- "Give me a campaign digest for September compared with August."
- "Which campaigns performed worst this week, and why?"

See [examples/weekly-digest.md](examples/weekly-digest.md) for an illustrative output.

## How it gets the numbers

There is no dedicated campaign statistics tool in Loomi Connect. The skill counts the `campaign` event by status with EQL (after checking the cost), uses saved reports when the project has them, and uses the campaign calendar to see what was scheduled and its reach. The EQL patterns are in [references/eql-campaign-metrics.md](references/eql-campaign-metrics.md). `scripts/summarise_campaign_counts.py` turns the counts into rates, changes and flags.

## Notes and limitations

- Opens and clicks are counted as events, not unique customers.
- On large projects, every EQL query over campaign events scores `high` in `estimate_eql_cost`. The skill runs only bounded, single-breakdown queries, and splits anything scoring `very_high`.
- EQL is rate-limited to about one query every 3 seconds, so a digest takes a minute or two.
- Attributed revenue lives in the Engagement UI's campaign evaluation. The skill reports revenue only when a saved report or a UTM property on purchases provides it.
- `search_email_campaigns` lists standalone email campaigns only. Emails sent from scenarios show up in the calendar and in campaign events.
- The campaign calendar lists planned times for draft scenarios too, and doesn't list event-triggered sends.
