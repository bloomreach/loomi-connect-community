# Facet rule fixer

Applies facet (filter) changes in Bloomreach Discovery: boost, bury, hide or always show facets in global, site search and category facet rules, such as the ones `facet-optimizer` recommends or "show Size first on dresses". It finds the rule that already covers each page and updates it instead of adding a duplicate, creates new rules switched off, blocks pages in a running A/B test, plans each change with its before and after state, the exact tool call and an undo, and writes only after an explicit yes.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: creates facet rules (switched off), switches them on (each switch-on its own yes), changes facet rules (boost, bury, hide, always show, name, audience, on or off) and deletes facet rules (each delete its own yes), with `create_facet_rule`, `update_facet_rule` and `delete_facet_rule`, each after you confirm |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `list_facets_global`, `list_site_search_facets`, `list_category_facets`, `get_facet_rule`, `list_facet_attributes`, `list_categories`, `search_discovery_experiments`, `search_discovery_product_grid_insights`; writes: `create_facet_rule`, `update_facet_rule`, `delete_facet_rule` |
| **Other requirements** | Python 3 for `scripts/facet_rule_plan.py` (standard library only) |
| **Tested with** | Claude Code (plan script on synthetic data; reads and tool schemas checked on a demo account; no live writes) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Apply the facet optimizer's recommendations in staging"
- "Show Size first on the dresses category"
- "Hide internal_sku on every search and category page"

## Example output

See [examples/apply-facet-review.md](examples/apply-facet-review.md).

## Notes and limitations

- Discovery writes go live once Discovery syncs, usually within minutes. A global rule changes every search and category page. Deletes are permanent: the undo recreates the rule with a new ID.
- New rules are created switched off, because `create_facet_rule` makes them live by default. Every switch-on and every delete is confirmed on its own.
- The account and environment are always asked for; the skill never falls back to production.
- `update_facet_rule` merges on the server: each facet list sent replaces that list, and an omitted or `null` field keeps its value, so a name, schedule or audience can't be cleared once set. Whether an empty list clears a facet action hasn't been tested; the plan warns and `verify` shows the result.
- Value merges, renames, range buckets and value order can't be set through Loomi Connect; the skill gives dashboard steps for those.
- The plan uses the shared plan-file shape (docs/skill-authoring.md), and `facet_rule_plan.py verify` checks every write from the read-backs.
- The write payloads follow the tools' published schemas; they haven't been run against a live account while building the skill.
