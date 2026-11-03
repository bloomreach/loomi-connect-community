# Lifecycle coverage map

Checks which of the eight standard lifecycle flows a Bloomreach Engagement project runs: welcome, browse abandonment, cart abandonment, post-purchase and review, replenishment, birthday or anniversary, win-back, and sunset or re-permission. It:

- finds the scenarios that do each job, judged by their trigger and nodes rather than their names;
- classifies each flow as live, weak (live but disconnected, late or with no message step), stopped, draft or missing;
- sizes the monthly audience of each missing or weak flow with aggregate EQL counts;
- puts a revenue figure on each gap, with every assumption shown;
- hands off to `engagement-scenario-builder` to build, `scenario-qa` to check and `engagement-scenario-performance` to measure.

It uses aggregate counts only and never changes anything. `funnel-leak-finder` goes deeper on the cart, browse and post-purchase flows (funnel drop-off and its value); this skill covers the whole lifecycle.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_event_schema`, `get_customer_property_schema`, `get_consent_settings` (via `call_tool`), `search_scenarios`, `search_scenario_nodes` (via `call_tool`), `search_email_campaigns`, `search_sms_campaigns`, `estimate_eql_cost`, `execute_analytics_eql` |
| **Other requirements** | None. Python 3 is optional, for the bundled script |
| **Tested with** | Claude Code (manual read-only run, November 2026, on a demo project): scenario lists with and without `trigger_types` filters, scenario definitions and graph maps read for a welcome and a birthday template, and the welcome audience query estimated (`medium`). The other audience queries are shapes that ran in `winback-opportunity` and `segment-opportunity-finder`, not run for this skill. `scripts/lifecycle_coverage.py` tested on synthetic fixtures. Not tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Which lifecycle flows are we missing?"
- "Do we have a welcome series, a birthday email and a win-back flow, and are they live?"
- "Audit our automation coverage and tell me which flow to build next."
- "What's it worth to switch on the flows we've left in draft?"

See [examples/illustrative-coverage.md](examples/illustrative-coverage.md) for an example output. Its names and numbers are illustrative.

## Scripts

- `scripts/lifecycle_coverage.py` (Python 3 standard library, no network): reads saved scenario definitions, the scenario list and the audience counts, and returns each flow's status with evidence, problems, monthly audience, value and value at stake, priority and hand-off. Flow definitions, conversion assumptions and thresholds are in [references/rules.json](references/rules.json).

## Notes and limitations

- Scenario list records don't show the trigger, so the skill filters by trigger type and reads each candidate's definition. Name-only matches are reported as unconfirmed and never count as coverage.
- Template scenarios can have their trigger left unconnected. The skill checks the connections, so such a flow shows as weak even when it's active.
- Conversion rates are conservative planning assumptions, not benchmarks; use your own results where you have them. One customer can be in several flows, so the total is "up to".
- Sunset and re-permission flows protect deliverability rather than earn revenue, so they get no money figure.
- Standalone recurring campaigns can do the job of a win-back or sunset flow; they're mentioned as partial cover but don't change a flow's status.
