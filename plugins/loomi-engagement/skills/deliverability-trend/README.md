# Deliverability trend

Trends email deliverability in a Bloomreach Engagement project over a longer window (default 90 days, by week): delivery, hard and soft bounce, spam complaint and unsubscribe rates. It flags rule-of-thumb guard-rail breaches (such as the 0.1% and 0.3% complaint rates in bulk-sender guidance), gradual drift against the project's own earlier weeks, and single-week spikes, and traces them by sending domain or integration, scenario vs one-off campaign, new vs established recipients, and the sends behind each spike. It uses aggregate counts only and never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_event_schema`, `estimate_eql_cost`, `execute_analytics_eql`, `search_scenarios` |
| **Other requirements** | Python 3 for `scripts/deliverability_trend.py` (standard library only); the steps also work by hand |
| **Tested with** | Claude Code: the daily trend, sender and new-audience queries run read-only on a demo project (about 1.2 million customers; each scored `high`); the script against synthetic data. The demo project records no sender, so the by-domain view hasn't been seen with real values. |
| **Maintainer** | Bloomreach |

## Example prompts

- "Is our email deliverability getting worse?"
- "Spam complaints feel high lately. Are we near the 0.3% limit?"
- "Show me the bounce trend for the last quarter and what's behind it."

See [examples/quarter-trend.md](examples/quarter-trend.md) for an illustrative output.

## How it works

1. One EQL query counts `campaign` events for email by day and status over the window; the script sums them into Monday-to-Sunday weeks and works out each week's rates with exact fractions.
2. It compares the last four weeks with the weeks before, and every week with the guard-rails and the typical week.
3. Breakdown queries (sender, campaign, new recipients, spike weeks) show where problems come from. The queries are in [references/eql-deliverability.md](references/eql-deliverability.md); thresholds and status names are in `references/rules.json`.

## Notes and limitations

- The guard-rails are widely quoted rules of thumb, not Bloomreach or mailbox-provider limits for your account. Mailbox providers measure complaints on their own data (for example Gmail Postmaster Tools), which this skill can't see.
- Rates are event counts, not unique customers.
- `sender` and `campaign_trigger` can be empty on the campaign event; scenarios are told apart from one-off campaigns by matching `campaign_id` against `search_scenarios`.
- Status names differ between projects (`hard_bounced` or `hard_bounce`, `unsubscribed` or `unsubscribe`); `references/rules.json` maps both.
- For one period's results per campaign, use `engagement-campaign-digest`.
