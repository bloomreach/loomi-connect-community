# Discovery rule cleanup

Applies a Bloomreach Discovery merchandising rule cleanup, usually the list from `discovery-rule-audit`: disables expired, duplicate or dead-traffic ranking and facet rules, sets missing end dates, retargets rules to the wording shoppers use, and deletes old disabled rules on a separate confirmation. Every change is planned with its before and after state and its undo, checked for impact and running A/B tests, written to staging first, and confirmed by reading the rule back.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: disables, end dates and queries of ranking and facet rules (`update_ranking_rule`, `update_facet_rule`), and deletes of disabled ranking and facet rules (`delete_ranking_rule`, `delete_facet_rule`), each after confirmation |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `get_ranking_rule`, `get_facet_rule`, `get_discovery_media_rule`, `search_discovery_experiments`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `search_discovery_product_grid_insights`, `update_ranking_rule`, `delete_ranking_rule`, `update_facet_rule`, `delete_facet_rule` |
| **Other requirements** | Python 3 for `scripts/cleanup_plan.py` (standard library only) |
| **Tested with** | Claude Code (the plan script against synthetic rules; write payloads from the tools' published schemas) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Apply the rule audit's clean-up list"
- "Disable the expired ranking rules that are still on"
- "Delete the old disabled rules for jeans"

## Notes and limitations

- **Discovery changes are live immediately**, and deletes can't be undone. The skill asks before each batch, separately before deletes, and separately before production.
- It never deletes an enabled rule: that becomes a disable, and the delete can follow later.
- Media rules (banners) have no write tool in Loomi Connect, so the skill gives dashboard steps. Redirects go to `discovery-redirect-fixer`.
- The update tools can't clear an end date. If a rule had none, undoing a new end date means clearing it in the dashboard; the plan says so.
- Rules in a running A/B test are never changed.

See [examples/cleanup-batch.md](examples/cleanup-batch.md).
