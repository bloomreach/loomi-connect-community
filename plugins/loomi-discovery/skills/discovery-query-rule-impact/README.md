# Discovery query rule impact

Shows what each merchandising rule does to one Bloomreach Discovery search query or category page, and estimates whether it helps or hurts revenue. It compares the live product grid with the same grid with each ranking rule switched off, with all ranking algorithm rules off, and with every rule off, then reports per rule the products it pins or boosts, moves and hides, an estimated revenue effect and a verdict (helps, neutral, hurts, hides sellers). It never changes a rule.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `search_discovery_product_grid_insights`, `get_discovery_product_performance_table`, `get_discovery_product_performance`, `get_ranking_rule` (optional) |
| **Other requirements** | Python 3 for `scripts/rule_impact.py` (standard library only); the comparison also works by hand |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## Example prompts

- "What are the rules on 'dress' actually doing? Are any of them costing us money?"
- "Is the pin rule on 'black dress' worth keeping?"
- "Show me the Outerwear category with and without merchandising."

## How it works

1. Takes the query's visits, revenue and product views per visit from the query performance table (the exact row; `search=` is a substring match).
2. Fetches the baseline grid, then one grid per ranking rule with that rule in `disabled_customization_ids`, one with all ranking algorithm rules off and one with everything off. Every response is saved to a file and parsed by `scripts/rule_impact.py`, never read into the conversation.
3. Fetches revenue per visit for the products that move.
4. The script compares positions, reads `merchandisingRulesApplied` from the score breakdown, compares `numFound` and product IDs to find hidden products, and estimates each rule's effect: Σ (position weight with the rule − weight without) × product RPV × query visits, using the curve in `references/rules.json`.

See [examples/pin-rule-on-gown.md](examples/pin-rule-on-gown.md).

## Notes and limitations

- **Product RPV is product-wide**, across all the product's traffic, not this query. No Loomi Connect tool gives a product's RPV for one query; that would make the estimate much better, and is a request to the Loomi Connect team.
- The position-weight curve is an **assumption**. Its total is scaled to the query's product views per visit, but its shape isn't measured.
- The estimate ignores substitution (shoppers buying something else instead), so treat it as direction and rough size. To know, A/B test the rule with `discovery-experiment-setup`.
- Only ranking and ranking algorithm rules can be switched off in the preview. Synonyms, redirects and facet rules aren't removed by `disabled_customization_ids`, so they aren't measured.
- The grid shows a default shopper: audience-targeted rules, personalisation and A/B test buckets differ for real shoppers.
- The tool description says active rule IDs are at `debug.experiments`; they're at `debug.request.experiments` (ranking rules only), and `debug["customizations.explain"]` has every rule type, which this skill uses (see [known tool behaviour](../../../../docs/known-tool-behaviour.md)).
