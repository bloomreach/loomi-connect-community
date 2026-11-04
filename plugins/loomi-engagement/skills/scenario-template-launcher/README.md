# Scenario template launcher

Starts a new Bloomreach Engagement scenario from something proven: an existing scenario in the same project or another project you can access, cloned with Engagement's clone-to-project workflow. It previews the clone, lists every reference that won't resolve in the target project (events, properties, consent categories, frequency policies, integrations, catalogs, project variables and IDs) with how to fix each, shows exactly what will be created, clones once as a **draft** after an explicit yes, reads it back to check it, and hands it to `scenario-qa`. When no scenario fits, it lists Bloomreach's predefined email and SMS templates for the flow and hands the outline to `engagement-scenario-builder`.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: clones one scenario into the target project as a draft (`clone_scenario`), with the dependencies it needs that the target doesn't have, after you confirm. Never uses `replace`, never starts, edits or deletes a scenario |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_scenarios`, `search_scenario_nodes`*, `list_predefined_templates`*, `preview_clone_scenario`*, `get_event_schema`, `get_customer_property_schema`, `get_consent_settings`*, `get_frequency_policies`*, `search_integrations`, `search_catalogs`, `list_project_variables`, `search_recommendations`; write: `clone_scenario`* (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | Python 3 for `scripts/scenario_clone_plan.py` (standard library only), optional |
| **Tested with** | Claude Code: `preview_clone_scenario`, `list_predefined_templates` and the target look-ups were called read-only against demo projects, within one project and across two. The script was tested on synthetic data. No live clone was run while building the skill. Not yet tested in an OpenAI client |
| **Maintainer** | @bloomreach |

## Example prompts

- "We have no browse abandonment flow. Copy the one from our EU project into the UK project."
- "Clone the 'Welcome series' scenario as a new draft so we can try a different first email."
- "Start a win-back flow from the one we built in the sandbox."

See [examples/browse-abandonment-from-sister-project.md](examples/browse-abandonment-from-sister-project.md) for illustrative output.

## How it works

1. **Gap and source:** agrees which flow is missing, then shortlists existing scenarios that do the job, in the target or in projects you name, and lets you pick one.
2. **Preview:** `preview_clone_scenario` lists what the clone carries and whether the target already has each item.
3. **Fix list:** `scenario_clone_plan.py plan` checks every event, property, consent category, frequency policy, integration, catalog, project variable and ID the source uses against the target, and builds the `clone_scenario` payload.
4. **Confirm, clone, verify:** shows what will be created, reused and copied, waits for a yes, clones once, checks the read-back with `verify`, and hands off to `scenario-qa` and `engagement-scenario-builder`.

## Notes and limitations

- **No scenario templates in Loomi Connect.** `list_predefined_templates` covers weblayers, snippets, emails, blocks, custom rows, SMS and in-app messages, with names and tags only. A whole flow comes from cloning an existing scenario.
- **Never `replace`.** For items the target already has, the clone reuses the target's (`use_old`) or makes a copy (`duplicate`). `replace` would overwrite items live scenarios and campaigns use.
- **Webhooks.** Cloning copies webhook headers and bodies, which often hold API tokens, into the target. The skill never shows them, and warns before you confirm.
- **Between organisations.** A copy from a project in another organisation is blocked until you confirm it in your own words, and always blocked when the source has webhook steps (it would copy one client's tokens into another's project).
- **Retries.** After a failed clone it checks whether the clone was made anyway, and if not, previews and plans again before asking you again.
- **References the clone keeps as names or IDs** (events, consent categories, integrations, catalogs and so on) aren't remapped. The fix list says what to change in the draft; nothing is fixed automatically.
- **Plan file.** The plan uses the shared plan-file shape (docs/skill-authoring.md) with the target's `project_id` and `project_name`. Its `undo` is empty because the skill never deletes; delete an unwanted clone in the Engagement UI.
