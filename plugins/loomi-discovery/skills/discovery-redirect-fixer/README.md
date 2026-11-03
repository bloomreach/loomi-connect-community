# Discovery redirect fixer

Applies fixes to Bloomreach Discovery keyword redirects: create, update or delete, such as the ones `discovery-redirect-audit` or `discovery-search-category-match` recommend. It plans each change with its before and after state, the exact tool call and an undo, checks it (keyword conflicts, URL, revenue taken from product results, running A/B tests), creates new redirects switched off, and writes only after an explicit yes.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: creates redirects (switched off), switches them on, changes redirects (URL, match type, keywords, name, schedule, audience, on or off) and deletes redirects, each after you confirm; deletes each need their own yes |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `search_redirects`, `get_discovery_query_performance`, `search_discovery_experiments`, `search_discovery_product_grid_insights`; writes: `create_redirect`, `update_redirect`, `delete_redirect` |
| **Other requirements** | Python 3 for `scripts/redirect_plan.py` (standard library only) |
| **Tested with** | Claude Code (plan script on synthetic data; reads checked on a demo account; no live writes) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Fix the redirects the audit flagged: add https to 'returns' and make 'sale' an exact match"
- "Add a redirect from 'track order' to our order status page"
- "Switch off the Black Friday redirects"

## Example output

See [examples/fix-redirect-audit-findings.md](examples/fix-redirect-audit-findings.md).

## Notes and limitations

- Redirect changes go live once Discovery syncs, usually within minutes. Deletes are permanent: the undo recreates the redirect with a new ID. The skill offers switching off instead.
- New redirects are created switched off, because `create_redirect` makes them live by default.
- Discovery silently ignores a keyword that another redirect already has, so the plan blocks those.
- `update_redirect` can't clear a schedule or audience once set (an omitted field keeps its value); that undo is done in the Discovery dashboard.
- Staging and production have separate rules, so each environment gets its own plan.
- The write payloads follow the tools' published schemas; they haven't been run against a live account while building the skill.
