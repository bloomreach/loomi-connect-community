# Engagement journey health

Checks all live Bloomreach Engagement scenarios at once and answers "which of my journeys are broken, not sending or suppressed right now, and how do I fix them?". It counts what each message step actually did over the last few weeks (delivered, suppressed, aborted, failed), compares it with the period before, and reads the conditions on the way to each step. You get a ranked list: what's wrong, the numbers that show it, and one fix per item. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_scenarios`, `search_scenario_nodes`*, `get_event_schema`, `get_customer_property_schema`, `estimate_eql_cost`, `execute_analytics_eql` (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | Python 3 for `scripts/journey_flags.py` (standard library only). The steps also work by hand. |
| **Tested with** | Claude Code: every step run read-only against a sandbox project with live `campaign` events (10 active flows, about 90,000 email and SMS events in 30 days). Not yet tested in an OpenAI client |
| **Maintainer** | @pavelsafarikbr |

## Example prompts

- "Which of our live journeys aren't working right now?"
- "Our welcome flow stopped sending. Why?"
- "Health check of all active automations: what's broken or not sending?"
- "Are any of our trigger flows suppressing most of their recipients?"

See [examples/journey-health-check.md](examples/journey-health-check.md) for output from a test run.

## How it differs from nearby skills

All of these look at scenarios; this one looks at **all live flows at once, after sending**, and asks whether each is broken, not sending or suppressed.

- `engagement-scenario-performance`: how well one flow performs, step by step (opens, clicks, purchases after, splits).
- `lifecycle-coverage-map`: which lifecycle stages have no flow at all.
- `engagement-scenario-explainer` audit mode: structure and housekeeping (stale drafts, disconnected nodes, missing references), mostly without numbers.
- `scenario-qa`, `campaign-qa`, `engagement-send-preflight`: content checks **before** sending (links, Jinja, compliance, spam risk).
- `deliverability-trend`: why email delivery dropped, by error code, mailbox provider and campaign.

## How it gets the numbers

Every message a scenario sends records a `campaign` event with the scenario's ID, the step's node `id` and a `status`. One EQL cross-tab per period gives every flow and step by status; `scripts/journey_flags.py` turns the two cross-tabs into per-step shares and flags, with thresholds in `references/rules.json`. The reason a message wasn't sent is in the event's `message` property. Queries are in [references/queries.md](references/queries.md) and the checks in [references/checks.md](references/checks.md).

## Notes and limitations

- Email records `enqueued` and then `delivered` or `hard_bounced` / `soft_bounced`. SMS and push record `sent` with no `delivered`, so their delivery is reported as unknown, not as lost.
- `action_type` also holds scenario plumbing (splits, property updates, added events) and weblayer events. These aren't messages and are left out. `action_type` values are case sensitive.
- An active flow that sent nothing is traced to the first condition nobody passes when the condition can be counted with EQL. Conditions on segmentations, aggregates, expressions or Jinja are reported as "not sized".
- Each `campaign` event query rates high cost on large projects. A run needs about 4–12 queries, about 5 seconds apart.
- It never reads individual customers, and never repeats email addresses, IDs or message text found in conditions.
