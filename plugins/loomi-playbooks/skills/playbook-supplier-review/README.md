# Playbook: supplier review

Prepares a supplier or co-op conversation for one brand with evidence rather than opinion, by running existing skills in order: score the brand and find the queries it's buried on, A/B test a boost on the chosen query, read the result, close the test keeping the winner, and re-run the brand review to write the supplier talking points with the test's result. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session when the test has run.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-experiment-setup` creates a ranking rule or variant and an A/B test and starts it; `discovery-experiment-close` ends the test (live at once, can't be undone), fixes a rule left in the wrong state and archives it. Each write only after its own explicit "yes" |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_ranking_rule`, `create_ranking_rule_variant`, `update_ranking_rule`, `create_discovery_experiment`, `start_discovery_experiment`, `end_discovery_experiment`, `archive_discovery_experiment` |
| **Other requirements** | The `loomi-discovery` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "We meet Pacific next month about co-op funding. How are they doing, and would boosting them pay?"
- "Prove whether boosting our top denim brand on 'jeans' is worth it before we agree it with the supplier."
- "Carry on with the supplier review for Pacific." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| review | `brand-performance-review` | now |
| test | `discovery-experiment-setup` | now, after confirmations |
| read-out | `discovery-experiment-readout` | after the test has run (`min_test_days`, or the agreed end date) |
| close | `discovery-experiment-close` | after a conclusive read-out |
| talking-points | `brand-performance-review` | after the close |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the review, records each setup write, reads the close skill's plan and verify files into the change log, and prints what's next and when. See [examples/buried-brand.md](examples/buried-brand.md).

## Notes and limitations

- One test per run. To test the brand on another query, finish this run first, or start a new hand-off file.
- The talking points come from `brand-performance-review`, which writes a brand's supplier points; `qbr-report` covers the whole account's quarter instead.
- When no test runs, the test, read-out and close are skipped, and the talking points stand on the scorecard alone.
- The review's revenue at stake is an upper bound for the period. Only the read-out measures.
