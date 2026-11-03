# Quarterly business review

A QBR for ecommerce managers, from Bloomreach Discovery and (optionally) Engagement:

- **Headline KPIs**, the quarter against the previous quarter and the same quarter last year: revenue, revenue per visit, conversion and average order value, overall, for search, category and "other", and by device;
- **Wins and problems:** top searches and categories, the ones with problems ranked by revenue at stake, dead-end searches, and the searches, categories, products and brands that moved most;
- **Marketing:** email and SMS results quarter on quarter, and which always-on scenarios ran;
- **Experiments and work done:** A/B tests that ran and how they ended, and merchandising rules created or changed;
- **Risks**, and **three to five plays for next quarter**, each linked to the skill that does it.

It's the quarterly sibling of [weekly-ecommerce-briefing](../weekly-ecommerce-briefing/) and uses the same method, with thresholds sized for a quarter. You can ask for Discovery only, Engagement only, or both. It never changes anything.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `get_discovery_overall_performance`, `get_discovery_search_performance`, `get_discovery_category_performance`, `get_discovery_trend`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `get_discovery_product_performance_table`, `get_discovery_brand_performance`, `search_discovery_experiments`, `get_discovery_experiment_report`, `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `list_global_media_rules`, `search_redirects`, `get_pixel_health_status`, `search_discovery_catalogs`, `list_cloud_organizations`, `list_projects`, `get_campaign_calendar`, `search_scenarios`, `estimate_eql_cost`, `execute_analytics_eql` |
| **Other requirements** | Python 3 for `scripts/qbr_numbers.py` (optional; standard library only) |
| **Tested with** | Claude Code (read-only calls in November 2026 on a Bloomreach demo account and demo project, to check quarter windows with explicit comparison dates, a same-quarter-last-year comparison with no data, and the experiment, rule and scenario list shapes. Not yet run end to end on an account with a full year of data. The script is tested on synthetic fixtures) |
| **Maintainer** | Bloomreach |

## Example prompts

- "Put together our Q3 QBR."
- "How did the quarter go compared with last quarter and last year?"
- "Quarterly review for search and email, with what we should do next quarter."

See [examples/example-qbr.md](examples/example-qbr.md) for an illustrative output.

## Scripts

- `scripts/qbr_numbers.py`: reads the saved KPI cards (quarter vs previous quarter, and vs the same quarter last year), the performance tables, and the experiment and rule lists, and prints the three-way KPI table, the top and problem searches and categories, the movers, and the work done in the quarter as JSON. Thresholds are in `references/rules.json`. Standard library only; no network access.

## Notes and limitations

- Every Discovery call passes explicit quarter dates and comparison dates; without them the comparison is "the same number of days before", which isn't the previous quarter.
- A comparison period with no data returns zeros, not an error. The script reports "no data for the same quarter last year" instead of −100%.
- Rule lists show only each rule's last edit, so "rules changed in the quarter" undercounts rules edited again since.
- Engagement campaign revenue isn't available from Loomi Connect; the QBR doesn't estimate it.
- For the "why" behind a big move, use [revenue-anomaly-explainer](../revenue-anomaly-explainer/).
