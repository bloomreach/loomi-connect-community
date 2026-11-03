# Discovery synonym fixer

Applies synonym fixes in Bloomreach Discovery after you confirm them. It takes the fixes `discovery-synonym-review` or `discovery-zero-results-triage` recommend, or your own, and for each one builds a plan with the state before and after, the exact change and the undo. It checks for no-ops, duplicates, term rules, direction and running tests, previews the effect on search, offers staging first, and writes only after a yes per batch, with a separate yes for every delete.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: creates, updates, enables, disables and deletes user synonyms (`create_synonym`, `update_synonym`, `delete_synonym`), each batch after an explicit yes and each delete after its own |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `list_synonyms_user`, `list_synonyms_br_generated`, `search_discovery_experiments`, `search_discovery_product_grid_insights`, `get_discovery_query_performance`, `create_synonym`, `update_synonym`, `delete_synonym` |
| **Other requirements** | Python 3 for `scripts/synonym_plan.py` (standard library only) |
| **Tested with** | Claude Code (plan script and read calls; the write payloads come from the tools' published schemas) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Apply the synonym fixes from the review"
- "Add a two-way synonym for tshirt, t-shirt and t shirt"
- "Disable the synonym that maps furniture to necklace"

## Example output

See [examples/example-plan.md](examples/example-plan.md).

## Notes and limitations

- Synonym changes reach search after the next sync, about once an hour in production.
- Bloomreach-generated synonyms can't be changed with the Loomi Connect tools. Disable one in the dashboard first (it becomes "User Modified"), or add a user synonym, which applies alongside it.
- Deleting a "User Modified" synonym re-enables the Bloomreach-generated original. The skill plans that as a revert and recommends disabling instead.
- `update_synonym` defaults to one-way and enabled, so the skill always sends every field.
- New synonyms are created switched off and switched on as a separate change with its own yes; `create_synonym` would otherwise create them on.
- The plan follows the shared plan-file shape for write skills, and `synonym_plan.py verify` checks the read-back after each batch.
