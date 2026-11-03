# Contactability audit

Shows how much of a Bloomreach Engagement customer base can actually be reached, and whether that's getting better or worse. It:

- measures, per channel (email, SMS, push), the share of the base with the identifier and the share that also has the consent, and the gap between them;
- counts customers reachable on any channel, and high-value customers who can't be reached on any;
- tracks opt-ins against opt-outs month by month from consent events, flagging a shrinking list and opt-out spikes;
- finds consent categories that are defined but never used, and consent events for categories that aren't defined;
- returns prioritised findings, with hand-offs to `segment-opportunity-finder` and `engagement-segment-builder` for re-permission audiences.

It uses aggregate counts only, never lists customers, and never changes anything. `segment-opportunity-finder` sizes one "large group without consent" audience; this skill is the full picture behind it.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_customer_property_schema`, `get_event_schema`, `get_consent_settings` (via `call_tool`), `estimate_eql_cost`, `execute_analytics_eql`, optionally `search_scenarios`, `search_email_campaigns`, `search_sms_campaigns` |
| **Other requirements** | None. Python 3 is optional, for the bundled script |
| **Tested with** | Claude Code (manual read-only run, November 2026, on a demo project): consent settings and customer property schema read; the email-reachable count, the high-value-unreachable count, the monthly consent cross-tab and the consent-by-category cross-tab run as aggregate EQL, with their cost ratings recorded. The base, identifier and holder counts are shapes that ran in other skills. `scripts/contactability_report.py` tested on synthetic fixtures. Not tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "How many of our customers can we actually email?"
- "Are we gaining or losing email subscribers month by month?"
- "How many of our best customers can't we contact at all?"
- "Do we have consent categories nobody uses?"

See [examples/illustrative-contactability.md](examples/illustrative-contactability.md) for an example output. Its names and numbers are illustrative.

## Scripts

- `scripts/contactability_report.py` (Python 3 standard library, no network): reads saved aggregate counts, the consent settings and the consent-event cross-tabs, and returns reach shares, the consent gap, the monthly trend, category use and prioritised findings. Thresholds are in [references/rules.json](references/rules.json).

## Notes and limitations

- Consent categories aren't tied to channels in Engagement. The skill works out which category each channel uses from scenario send steps or by asking.
- Consent can be kept outside Engagement categories, for example as shop-platform customer properties. The skill checks for this before reporting low reach.
- Push tokens aren't always customer properties; if there's none in the schema, push reach is reported as not measurable rather than zero.
- The monthly consent breakdown must cap the number of months (`grouping top N`), and consent-event breakdowns over 365 days are rated `very_high`, so the skill keeps them to 6 months and 180 days.
- Legitimate-interest categories are granted by a filter rather than by consent events, so they're never flagged as unused.
