# Discovery experiment setup

Guides the setup of a Bloomreach Discovery A/B test for a ranking rule, or between two ranking algorithms, so the change is measured before it goes live for everyone. It checks for running tests and conflicting rules, looks at the query's traffic and live results, drafts the rule, previews its effect, estimates how long the test must run, and shows the full plan. It then creates the rule (disabled) and the experiment (draft), and starts the test, each only after its own explicit "yes".

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: creates a ranking rule (disabled), creates an experiment (draft), and starts the experiment. When a rule already exists (Pattern 2), it instead creates a variant of that rule (disabled) and enables it once the draft experiment exists, which may make it live for all shoppers of the query until the test starts. To test a ranking algorithm (Pattern 3), it creates a variant of today's algorithm rule pointing at the new algorithm (enabled the same way), or, where the account default ranks the pages, a new algorithm rule (disabled). Each write needs explicit confirmation. Starting a test is live immediately |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `search_discovery_experiments`, `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `get_ranking_rule`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, `search_discovery_product_grid_insights`, `search_ranking_algorithms`, `get_discovery_search_performance`, `get_discovery_category_performance`, `create_ranking_rule`*, `create_discovery_experiment`, `start_discovery_experiment`; for Patterns 2 and 3 also `create_ranking_rule_variant`*, `update_ranking_rule`* (* found with `search_tools` and run with `call_tool`) |
| **Tested with** | Claude Code: the read-only steps (pre-flight checks, preview and sizing) were run against a demo account. **The writes are untested.** No rule or experiment was created; the write payloads were checked against the tool schemas only |
| **Maintainer** | Bloomreach |

## Example prompts

- "For 'mens belt', boost Tommy Hilfiger and Pacific and bury duplicate listings, but A/B test it first."
- "Set up an A/B test of a ranking rule for the dresses category."
- "I want to test pinning our new arrivals for 'sneakers' before rolling it out."
- "A/B test the corrected copy of our search ranking algorithm against the current one."

See [examples/mens-belt.md](examples/mens-belt.md) for a full example plan.

## Notes and limitations

- **Writes are untested.** In particular, it isn't confirmed whether `create_discovery_experiment` accepts a disabled rule. If it doesn't, the skill stops and explains the trade-off rather than enabling the rule on its own.
- `create_ranking_rule` defaults to `enabled: true` (live for everyone). The skill always sends `enabled: false`.
- A rule can't be previewed before it exists, so `scripts/simulate_rerank.py` gives an offline, strongest-case preview from the live grid. The real effect depends on the boost strength.
- `scripts/estimate_duration.py` estimates the test length. Both scripts use the Python standard library and make no network calls.
- Implicit invocation is turned off for OpenAI clients (`agents/openai.yaml`), because this skill writes.
- **Algorithm tests (Pattern 3)** were planned from the tool schemas and a read of a demo account's algorithm rules and experiments; no algorithm rule or experiment was created. Whether `create_ranking_rule` with only `ranking_algo_id` reads back as a `ranking_algo` rule is untested; the skill checks the algorithm ID on the read-back. A page's algorithm rule doesn't appear in the ranking-rule lists, so the skill finds it in the product grid's debug output. There's no preview: the skill shows the two algorithms' weights side by side. Corrected copies come from [discovery-ranking-algorithm-fixer](../discovery-ranking-algorithm-fixer/).
- Use [discovery-experiment-readout](../discovery-experiment-readout/) to read the results.
