# Discovery autosuggest exclusions

Adds, changes or removes Bloomreach Discovery autosuggest exclusion rules, so bad search-as-you-type suggestions stop showing and wrongly excluded ones come back. It builds a change plan with a before/after preview of the suggestions and an undo for every change, creates new rules disabled, and writes only after an explicit yes for each batch, on staging first.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: creates autosuggest exclusion rules (disabled), enables, disables and changes the keywords of exclusion rules, and deletes a rule only when you ask, each batch after you confirm |
| **Loomi Connect tools** | `search_autosuggest_exclusion_rules`, `get_autosuggest_results`, `get_discovery_query_performance`, `list_discovery_accounts`; writes: `create_autosuggest_exclusion_rule`, `update_autosuggest_exclusion_rule`, `delete_autosuggest_exclusion_rule` (found with `search_tools` and run with `call_tool`) |
| **Other requirements** | Python 3 for `scripts/exclusion_plan.py` (standard library only) |
| **Tested with** | Claude Code (scripts and read calls; the write payloads come from the tools' published schemas) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Exclude 'dress fabric' and 'dress color' from autosuggest."
- "Apply the exclusions the autosuggest audit recommended."
- "Scharf is a brand we sell, stop hiding it in autosuggest."

See [examples/exclude-attribute-suggestions.md](examples/exclude-attribute-suggestions.md).

## How it keeps changes safe

- New rules are created **disabled**; enabling them is a separate batch that says it's live.
- Each batch needs its own yes. Deletes are offered only when you ask, each on its own, with "disable instead" offered first.
- The plan is saved to a file with the undo for every change before anything is written.
- It warns before excluding a keyword that is itself a real search, a very short keyword, or one with wildcard characters.
- It runs on staging first where the account has one, and asks again for production.
- After each batch it reads the rules and suggestions back and reports what's in place.

## Notes and limitations

- Exclusion rules are account-level; they can't be scoped to one site, only to one catalog (`domain_key`).
- Keywords are exact suggestions. The tools document exact matching, but none of this skill's checks could watch a live rule apply, so it checks after sync that only the exact suggestion went.
- `bulk_update_autosuggest_exclusion_rules` isn't used: one change per call is easier to review.
- Rules can take seconds to minutes to sync, and suggestions a little longer to disappear.
