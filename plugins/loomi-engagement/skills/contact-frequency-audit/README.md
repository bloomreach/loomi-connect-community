# Contact frequency audit

Measures how many messages customers actually received in a Bloomreach Engagement project over a window (default 28 days), per channel (email, SMS, push), as an aggregate distribution: how many customers got 1, 2–3, 4–7, 8–11 … messages, and the same per week. At each level it shows the opt-out rate (unsubscribed or complained) and the share who clicked, finds where fatigue starts, gives the share of recipients or of the base over a chosen cap, and recommends a frequency cap per channel with the evidence, compared with the project's frequency policies. It counts customers in buckets only, never lists them, and never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_event_schema`, `get_customer_property_schema`, `estimate_eql_cost`, `execute_analytics_eql`, `get_frequency_policies` |
| **Other requirements** | Python 3 for `scripts/frequency_distribution.py` (standard library only); the steps also work by hand |
| **Tested with** | Claude Code: the channel/status query and the per-threshold and opt-out customer counts run read-only on a demo project (about 1.2 million customers; counts scored `medium`); the script against synthetic data. The demo project's unsubscribers had no delivered email in the window, so a real fatigue curve hasn't been seen yet. |
| **Maintainer** | Bloomreach |

## Example prompts

- "Are we sending customers too many emails?"
- "How many texts did people get last month, and does it drive opt-outs?"
- "What frequency cap should we set for push?"
- "What share of our base got more than three emails a week?"

See [examples/email-sms-audit.md](examples/email-sms-audit.md) for an illustrative output.

## How it works

1. A status-mix query shows which channels the project sends and what "received" looks like for each (`delivered` for email, `sent` for SMS and push on the tested project).
2. EQL can't group customers by how many messages they got, so the skill counts customers who received at least K messages for a few thresholds, and the same with "and opted out" and "and clicked". The queries are in [references/eql-frequency.md](references/eql-frequency.md).
3. `scripts/frequency_distribution.py` turns the cumulative counts into buckets, rates, a fatigue point and a cap, with exact maths. Thresholds and rules of thumb are in `references/rules.json`.

## Notes and limitations

- It's many small queries (one per threshold and measure; see **Budget** in [references/eql-frequency.md](references/eql-frequency.md)), so it takes a couple of minutes at the EQL rate limit. Do one channel at a time.
- Heavy recipients are often the most active customers, so click share tends to rise with frequency; a rising opt-out rate is the more reliable signal.
- Opt-outs recorded on profiles that received nothing in the window (identity gaps, other sources) aren't in any bucket; the script warns when that's most of them.
- The default caps (`default_caps_per_week` in `references/rules.json`) are rules of thumb used only when the data shows no fatigue.
- For planned sends that would clash, use `engagement-send-collision-check`.
