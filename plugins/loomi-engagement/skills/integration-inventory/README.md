# Integration inventory

Lists how a Bloomreach Engagement project connects to the outside world: its integrations, API triggers and project variables, and every webhook step in its scenarios. It flags items that look unused (nothing in a scenario, campaign or weblayer refers to them), duplicated, disabled or misconfigured, credentials stored in project variables, webhook URLs or step headers, webhook steps that authenticate with an integration that no longer exists, API triggers nothing listens to, and templates that use variables that don't exist. It never repeats a secret: values, headers, bodies and full URLs are described ("an HTTP POST to an external host with an auth header"), and only hosts are shown. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_integrations`, `search_api_triggers`, `list_project_variables`, `search_scenarios`, `search_scenario_nodes`*, `search_email_campaigns`, `search_sms_campaigns`, `search_banners`, `search_in_app_messages` (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | None. Python 3 is optional, for the bundled script (standard library only) |
| **Tested with** | Claude Code, read-only, on a demo project: `search_integrations` (list and one detail), `search_api_triggers` (list and one detail), `list_project_variables` and `search_scenarios` (list and one detail with webhook steps), to confirm the fields returned. The script was tested on synthetic responses, including a test that no fixture secret reaches its output. Email, SMS, weblayer and in-app message details were not fetched live. Not run end to end, and not tested in an OpenAI client. |
| **Maintainer** | Bloomreach |

## Example prompts

- "What integrations does our Engagement project have, and are any unused?"
- "Are there API triggers nothing listens to?"
- "Clean up our project variables."
- "Are any API keys or tokens stored in plain text in our project?"
- "Why is this webhook failing?"

See [examples/illustrative-inventory.md](examples/illustrative-inventory.md) for an example output. Its names and numbers are illustrative.

## How it works

1. Lists integrations, API triggers (then each trigger's detail) and project variables.
2. Collects scenario, campaign, weblayer and in-app message definitions, the places these are referenced.
3. [scripts/integration_inventory.py](scripts/integration_inventory.py) matches references by ID and `project_variables.<name>`, describes each webhook step by method, host and authentication, and applies the checks with the rules in [references/rules.json](references/rules.json) (standard library only, no network). It never prints a value, header, body or full URL.
4. Returns a prioritised findings list and the four inventories.

## Notes and limitations

- `search_integrations` returns only `id`, `name` and `type`: no host, configuration, enabled state or last use. "Disabled" and most "misconfigured" checks rely on the webhook steps and API triggers instead, and the report says what couldn't be checked.
- Imports, exports and email or SMS delivery use integrations in ways Loomi Connect doesn't expose, so storage, SQL and delivery integrations are never called unused.
- Variable references are found only in the definitions fetched; email designs need `include_design=true`, and blocks and snippets aren't checked.
- Secret detection is pattern-based, so it can miss a credential with an innocent name and a plain-looking value.
- `search_email_campaigns`, `search_sms_campaigns` and `search_in_app_messages` can return HTTP 403; those are reported as not checked.
