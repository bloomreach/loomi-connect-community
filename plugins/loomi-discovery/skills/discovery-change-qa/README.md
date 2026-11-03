# Discovery change QA

Checks one Bloomreach Discovery merchandising change before it goes live: a ranking rule (boost, bury, pin, add to recall), a synonym, a redirect, a facet rule or a banner rule. It finds the searches and categories the change touches and their revenue, previews page one before and after on the live product grid, and returns a GO / GO WITH CAUTION / NO-GO verdict with a fix for each issue. It never makes the change.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `list_discovery_accounts` (only to match a name the user gives), `get_ranking_rule`, `search_redirects`, `get_facet_rule`, `list_synonyms_user`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `get_discovery_product_performance_table`, `search_discovery_product_grid_insights`, `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `list_site_search_media_rules`, `list_category_media_rules`, `list_global_media_rules`, `list_site_search_facets`, `search_discovery_experiments` |
| **Other requirements** | Python 3 for `scripts/change_preview.py` (standard library only); the checks also work by hand |
| **Tested with** | Claude Code |
| **Maintainer** | @bloomreach |

## What it checks

- **Scope:** the searches and categories the change touches (exact match, phrase match, global) and their visits and revenue.
- **Preview:** page one before and after for the top searches. Removing a rule uses the real grid with that rule disabled; a new or edited rule is simulated as its strongest case.
- **Ranking rules:** top sellers pushed off page one, off-topic or out-of-stock products moved up, boosted or pinned products that aren't in the results, one brand taking over, products both boosted and buried, two pins in one slot, very high strengths.
- **Synonyms:** no-ops, targets with no results or pointing the wrong way, expansions that bring in different products, duplicates.
- **Redirects:** missing, placeholder, non-web, http and scheme-less URLs, and phrase matches that catch searches that sell.
- **Clashes and schedule:** other enabled rules or redirects on the same queries, rules in a running A/B test, running tests that cover the queries, end dates in the past, promotions with no end date.

Thresholds and word lists are in [references/rules.json](references/rules.json).

## Example prompts

- "Before I switch it on, check this ranking rule for 'dress': boost Acme at 60 and pin product 1234 to slot 1."
- "What would rule 2118875 do if I enabled it?"
- "Is it safe to add a one-way synonym from 'frock' to 'dress'?"
- "QA this redirect: 'sale' to /sale, phrase match."

## Example output

See [examples/boost-rule-check.md](examples/boost-rule-check.md).

## Notes and limitations

- Discovery can't preview a rule that doesn't exist yet. The after grid for a new rule is the strongest possible effect (a hard sort); a real attribute boost blends with relevance by its strength.
- Product revenue comes from the site-wide product table, not per search.
- Stock is checked only if the catalog has one of the stock fields in `rules.json`; the grid drops fields it doesn't have.
- Rule lists hide audiences (`audienceName` is null), so two rules on one query may target different audiences.
- To A/B test the change instead of switching it on, use `discovery-experiment-setup`.
