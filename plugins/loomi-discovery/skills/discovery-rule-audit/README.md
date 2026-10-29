# Discovery rule audit

Audits every merchandising rule in a Bloomreach Discovery account or site and produces a prioritised cleanup list. It covers ranking rules, media rules (banners), facet rules and redirects, across site search, category and global scopes. It flags rules that are expired but still on, failing to sync, disabled and stale, never-ending but seasonal, duplicated or conflicting, attached to searches or categories with no traffic, or tied to A/B tests (including a test flag left on when no test is running). It never changes anything.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `list_site_search_media_rules`, `list_category_media_rules`, `list_global_media_rules`, `list_site_search_facets`, `list_category_facets`, `list_facets_global`, `search_redirects`, `search_discovery_experiments`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `get_ranking_rule`, `get_discovery_media_rule`, `get_facet_rule` |
| **Tested with** | Claude Code (manual run of the method against a demo account with about 150 rules; `scripts/audit_rules.py` tested on saved responses from that run) |
| **Maintainer** | Bloomreach |

## Example prompts

- "Audit our merchandising rules and tell me what to clean up."
- "Are there any expired or duplicate ranking rules?"
- "Which of our banners are on searches nobody uses?"

See [examples/example-apparel-audit.md](examples/example-apparel-audit.md) for an example output.

## Notes and limitations

- `scripts/audit_rules.py` (Python standard library, no network) reads the saved list responses and applies the checks. The assistant then confirms the important findings with the `get_*` tools.
- The rule lists don't show match type, and their `audienceName` can be null for rules that do target an audience. The skill fetches the full rule before calling two rules duplicates.
- Expiry is read from `durationTag`, because `syncStatus` isn't consistent for expired rules.
- Redirects aren't judged on search traffic, because redirected searches don't appear in it.
- Accounts with more than 100 rules of one type need several pages per list.
