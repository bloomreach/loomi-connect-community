# Playbook: ranking algorithm tune-up

Takes one Bloomreach Discovery ranking algorithm from "its weights look wrong" to "a corrected version ranks the pages and is holding up", by running six existing skills in order: review the Ranking Studio algorithms, make a corrected copy that ranks nothing yet, A/B test the copy against the algorithm ranking the pages today, read the result, keep the winning algorithm, and confirm it holds at full traffic. A live algorithm is never re-weighted in place. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session when the test has run.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-ranking-algorithm-fixer` creates a corrected copy of an algorithm (ranks nothing on its own); `discovery-experiment-setup` creates a variant of today's algorithm rule (or a new, disabled algorithm rule) pointing at the copy and an A/B test, enables the variant and starts the test; `discovery-experiment-close` ends the test (live at once, can't be undone), fixes a rule left in the wrong state and archives it. Each write only after its own explicit "yes" |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_ranking_algorithm`, `create_abr_algorithm`, `create_ranking_rule`, `create_ranking_rule_variant`, `update_ranking_rule`, `create_discovery_experiment`, `start_discovery_experiment`, `end_discovery_experiment`, `archive_discovery_experiment` |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our search algorithm leans almost entirely on margin. Fix it, but test it first."
- "Review our ranking algorithms and A/B test a corrected version of the worst one."
- "Carry on with the ranking algorithm tune-up." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| review | `discovery-ranking-algorithm-review` | now |
| copy | `discovery-ranking-algorithm-fixer` | now, after its yes |
| test | `discovery-experiment-setup` (Pattern 3) | once the copy is `Available`, after confirmations |
| read-out | `discovery-experiment-readout` | after the test has run (`min_test_days`, or the agreed end date) |
| close | `discovery-experiment-close` | after a conclusive read-out |
| confirm | `change-impact-tracker` | `measure_after_days` after the close |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it takes the review findings you pick, reads the fixer's and the close skill's plan and verify files into the change log, records each setup write, and prints what's next and when. See [examples/margin-heavy-search.md](examples/margin-heavy-search.md).

## Notes and limitations

- One algorithm per run, and the copy stage only makes a copy: an in-place re-weight, a rename or a delete is a separate `discovery-ranking-algorithm-fixer` job.
- Review findings a copy can't fix (errors, stuck training, unused algorithms, cross-type assignments) are listed and left out of the run.
- A page's algorithm comes from a `ranking_algo` rule, or the account default. An algorithm rule with an audience or a schedule can't be tested; the test stage then ends as `not_testable`.
- Pattern 3 of `discovery-experiment-setup` was planned from the tool schemas and a read of a demo account; its writes are untested.
- With a global algorithm rule, every search (or category) page changes at once, so `change-impact-tracker` has no unaffected pages to compare with; the A/B result is the stronger evidence.
- When today's algorithm wins, the copy is left in Ranking Studio, ranking nothing; retiring it is a separate job.
