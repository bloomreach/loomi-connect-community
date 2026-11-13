# Engagement scenario journey debugger

Answers "why didn't this customer get the message?" for **one customer in one scenario**. Engagement keeps no per-customer log of the nodes a customer passed, so the skill rebuilds the route: it reads the customer's events, walks the flow from the trigger along their branch, and uses the `campaign` events the scenario's actions and splits left behind as anchors that prove which way they went. You get the route, where it stopped, why, how sure it is, and one fix or check. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_customer_properties`, `list_customer_events`, `search_scenarios`, `search_scenario_nodes`*, `search_api_triggers`, `search_segmentations`, `search_customer_filters`, `search_event_segmentations`, `get_customer_attribute_values`*, `get_frequency_policies`*, `get_consent_settings`* (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | None |
| **Tested with** | Claude Code: read-only run against an internal test project, tracing one profile through an active Now-triggered scenario (project resolution, `search_scenarios` list and detail, `search_scenario_nodes` map and node detail via `call_tool`, `get_customer_properties`, `list_customer_events` for `campaign` and `merge`, `get_frequency_policies`); response shapes confirmed and the skill corrected where they differed. Not run: `get_consent_settings`, `get_customer_attribute_values`, segmentation and API-trigger lookups, On event and wait nodes, and a fresh-session triggering check. Not tested in an OpenAI client |
| **Maintainer** | @CWildeBloomreach |

## Example prompts

- "Why didn't this customer get the day-2 reminder from our browse abandonment flow?" (with the profile link)
- "Which path did this person take through the welcome journey?"
- "This customer bought last week but never entered the post-purchase scenario. Why?"

See [examples/day-2-reminder.md](examples/day-2-reminder.md) for a sample report.

## How it differs from nearby skills

- `customer-360-lookup`: a general summary of one customer (profile, timeline, scores, support flags), not a node-by-node trace.
- `engagement-journey-health`: all live flows at once, counted from `campaign` events, for flows that aren't sending for anyone.
- `engagement-scenario-explainer`: what a scenario does in general, and audits of stale or broken flows.

## Notes and limitations

- It takes a profile link or internal customer ID only, never an email address, to keep personal data out of the conversation and avoid the wrong profile after merges.
- Conditions, waits, limits and triggers leave no trace on the profile. Where no anchor settles a fork, the skill reconstructs past state from timestamps and says "likely" or "can't tell" rather than guessing.
- Loomi Connect can't see inbound API trigger calls, customer limit counters or past property values (only the current value and when it was last updated).
- Platform claims in `references/known-causes.md` are marked [doc] or [inference]; the [doc] items were checked against the Bloomreach documentation pages it lists on 13 Nov 2026.
