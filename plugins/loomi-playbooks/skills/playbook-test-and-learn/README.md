# Playbook: test and learn

Takes one Bloomreach Discovery search query or category page from "which rule is costing money?" to "the fix is rolled out and holding", by running five existing skills in order: measure what each rule does, A/B test a fix to the costliest one, read the result, roll out the winner, and confirm it holds at full traffic. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session when the test has run.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-experiment-setup` creates a ranking rule variant and an A/B test and starts it; `discovery-experiment-close` ends the test (live at once, can't be undone), fixes a rule left in the wrong state and archives it. Each write only after its own explicit "yes" |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_ranking_rule`, `create_ranking_rule_variant`, `update_ranking_rule`, `create_discovery_experiment`, `start_discovery_experiment`, `end_discovery_experiment`, `archive_discovery_experiment` |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: script tests against the real outputs of the stage skills' scripts. Not yet run end to end against a live test |
| **Maintainer** | @bloomreach |

## Example prompts

- "Find out which rule on 'black dress' is costing us money, and test a fix."
- "Carry on with the test-and-learn run for 'gown'." (with its hand-off file)
- "Our test on the dress rule should be done by now. What happened, and should we roll it out?"

## How it works

| Stage | Skill | When |
|---|---|---|
| find | `discovery-query-rule-impact` | now |
| test | `discovery-experiment-setup` | now, after confirmations |
| read-out | `discovery-experiment-readout` | after the test has run (`min_test_days`, or the agreed end date) |
| close | `discovery-experiment-close` | after a conclusive read-out |
| confirm | `change-impact-tracker` | `measure_after_days` after the close |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it turns the rule-impact result into findings, records each write, reads the close skill's plan and verify files into the change log, and prints what's next and when. See [examples/hurting-pin-rule.md](examples/hurting-pin-rule.md).

## Notes and limitations

- One finding per run. To test another rule on the same page, finish this run first: two tests on one query muddy each other.
- A rule targeted at an audience can't use the setup skill's Pattern 2; the test stage then ends as `not_testable`.
- The find stage's money is an estimate (see `discovery-query-rule-impact`). Only the read-out and confirm stages measure.
