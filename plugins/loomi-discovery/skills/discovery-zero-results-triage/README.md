# Discovery zero-results triage

Triages all of an account's dead-end searches at once: queries with no results, and queries whose results never get a click or a sale. For each query it checks what shoppers actually see, tries other wordings in both search modes, and puts it in one of four classes: synonym or spelling fix, catalog gap, redirect candidate, or noise. It returns one action list, ordered by the sessions at stake. It never changes anything.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `get_discovery_query_performance`, `search_discovery_product_grid_insights`, `search_redirects`, `list_synonyms_user`, `search_discovery_experiments` |
| **Tested with** | Claude Code (manual, read-only run of the method against a demo Discovery account with no sites, at account level). Not yet tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Which searches return nothing, and what should we fix first?"
- "Triage our zero-result queries."
- "Why do so many searches have no revenue?"

See [examples/example-apparel.md](examples/example-apparel.md) for a full example output.

## What it found in testing

- The `no_search_results` preset listed only 1 of 8 queries that return 0 products. The others appeared only under `no_revenue`. The skill always uses both.
- Hybrid search can return hundreds of off-topic products for a product the catalog doesn't carry, so the skill judges by titles and checks keyword-only mode too.
- Query-level search-settings rules (relaxation and spelling correction turned off) can force zero results. They appear only in the product grid's debug output.

## Notes and limitations

- Product grid responses are very large. The skill asks for few fields and rows, turns off facets, and includes `scripts/grid_summary.py` (standard library only) to summarise a saved response.
- `simple_debug=false` returned HTTP 500 errors in testing, so the skill doesn't use it.
- There is no read tool that lists query-level search-settings rules. The skill finds them in the product grid's `customizations.explain`.
- Revenue figures are estimates at the typical revenue per search session, not forecasts.
- `scripts/triage_candidates.py` (standard library only) suggests a likely fix for each dead-end query from the saved reports, synonyms and redirects, with the thresholds in `references/rules.json`. Its classes are suggestions: the product grid still decides each fix.
- For one query in depth, use [discovery-query-diagnosis](../discovery-query-diagnosis/).
