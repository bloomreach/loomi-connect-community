# Playbook: product opportunity

Takes one Bloomreach Discovery product from "this one is worth acting on" to "the change is rolled out and holding". Seven existing skills run in order: sort every product into opportunity groups, report the chosen product everywhere, suggest a better listing when the page is the problem, A/B test a boost or bury on its main query or category, read the result, roll out the winner, and confirm it holds at full traffic. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up when the test has run.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-experiment-setup` creates a ranking rule (or a variant) and an A/B test and starts it; `discovery-experiment-close` ends the test (live at once, can't be undone), fixes a rule left in the wrong state and archives it. Each write only after its own explicit "yes". The listing stage only suggests |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_ranking_rule`, `create_ranking_rule_variant`, `update_ranking_rule`, `create_discovery_experiment`, `start_discovery_experiment`, `end_discovery_experiment`, `archive_discovery_experiment` |
| **Other requirements** | The `loomi-discovery`, `loomi-product-data` and `loomi-platform` plugins; a client that can view images for the listing stage (it falls back to text). Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Which of our products are hidden gems? Pick the best one and test boosting it."
- "Product 10442 gets loads of views and doesn't sell. Work out why and fix it."
- "Carry on with the product opportunity run: the boost test should be done." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| find | `product-opportunity-finder` | now |
| report | `discovery-product-report` | now |
| listing | `product-data-enhancer` | now, when the listing is the problem |
| test | `discovery-experiment-setup` | now, after confirmations, when ranking is the problem |
| read-out | `discovery-experiment-readout` | after the test has run (`min_test_days`, or the agreed end date) |
| close | `discovery-experiment-close` | after a conclusive read-out |
| confirm | `change-impact-tracker` | `measure_after_days` after the close |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records the top products as findings, records each test write, reads the close skill's plan and verify files into the change log, and prints what's next and when. See [examples/hidden-gem-boost.md](examples/hidden-gem-boost.md).

## Notes and limitations

- One product and one test per run.
- A listing fix ends the run with suggestions for the feed team: no Loomi Connect skill writes product data, and `change-impact-tracker` measures merchandising changes, not feed changes. Re-run `discovery-product-report` after the import to see the effect.
- A query with an audience-targeted rule can't take the setup skill's Pattern 2; the test stage then ends as `not_testable`.
- The finder's money is an estimate. Only the read-out and confirm stages measure.
