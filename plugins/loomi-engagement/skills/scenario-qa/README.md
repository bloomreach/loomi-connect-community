# Scenario QA

Pre-launch QA for one Bloomreach Engagement scenario. It checks every email, SMS/MMS and mobile push step for broken links, Jinja personalization that renders badly for real profiles, compliance gaps (unsubscribe link, postal address, STOP/HELP, consent category), deliverability and spam risk. It then checks the whole flow for dead ends, orphaned steps and references to events or assets that don't exist. You get a GO / GO WITH CAUTION / NO-GO verdict, a triage table, and a paste-ready fix for each issue. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_scenarios`, `search_scenario_nodes`*, `get_event_schema`, `get_customer_property_schema`, `get_mapping`, `search_aggregates`, `search_catalogs`, `search_recommendations`, `get_consent_settings`*, `list_customers`, `get_customer_properties`, `list_customer_events` (* found with `search_tools` and run with `call_tool`) |
| **Tested with** | claude.ai, against a Bloomreach demo project (staging), 3-email welcome scenario |
| **Maintainer** | @jeffbird13-bloomreach |

## Example prompts

- "QA the 'Abandoned cart' scenario before we launch it."
- "Is our welcome journey ready to go live?"
- "Check the links, personalization and compliance in the post-purchase flow."
- "Proof every email and SMS in the Black Friday scenario."

See [examples/example-report.md](examples/example-report.md) for illustrative output.

## How it differs from engagement-scenario-explainer

`engagement-scenario-explainer` explains what a scenario does and audits every scenario in a project for stale drafts and broken references. `scenario-qa` goes deep on one scenario's **content** before launch: it fetches each step's design, renders Jinja against sample profiles, checks links, and applies channel compliance rules.

## Notes and limitations

- **Live link checks need web access.** In clients without it, links are listed as "couldn't verify" and the other checks still run. Links that return 401, 403, 429 or a bot challenge are also reported as "couldn't verify", never as broken.
- **Jinja rendering is simulated** against 3–5 sample profiles, chosen for varying data completeness unless you name test profiles. Personal values are masked in the report, and profiles are labelled A, B, C. Sandbox projects can still hold real customer data.
- **Compliance checks are guidance, not legal advice.** SMS carrier approval is outside the skill's control.
- Large scenarios (more than about 25 sends) take longer, because designs are fetched one step at a time. Link checks are capped at about 150 unique URLs per run.
- Some references, such as saved metrics used in Jinja, have no read tool and are reported as "not verified".
