# Playbook: second purchase

Takes one Bloomreach Engagement project from "how many first-time buyers come back?" to "a second-purchase flow is live, timed to our data, and here is whether the repeat rate moved", by running eight existing skills in order: measure the repeat-purchase cohorts and the time to a second order, find the missing or weak post-purchase or replenishment flow, clone a proven one as a draft, time its waits to the cohort curve, optionally add an A/B split to it, QA it, and once you have switched it on, read the test out, read its results and rebuild the cohorts. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `scenario-template-launcher` clones one scenario as a draft that never starts; `engagement-scenario-builder` creates or changes a draft scenario; `engagement-ab-test-setup`, if you want a test, adds an A/B split to the draft (or, for a running flow, makes a new draft copy with it). Each write only after its own explicit "yes". The playbook never switches a flow on: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `clone_scenario`, `create_scenario`, `update_scenario`, `update_scenario_node` |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Too few of our new customers buy a second time. Fix it and show me whether it worked."
- "When should we nudge first-time buyers, and do we have a flow that does it?"
- "Carry on with the second-purchase run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| baseline | `engagement-repeat-purchase-cohorts` | now |
| find | `lifecycle-coverage-map` | now |
| launch | `scenario-template-launcher` | now, after its confirmation |
| adapt | `engagement-scenario-builder` | now, after confirmations |
| test | `engagement-ab-test-setup` | now, after its confirmation (optional) |
| qa | `scenario-qa` | now; done when you switch the flow on |
| ab-read-out | `engagement-experiment-readout` | `readout_after_days` after the start (skipped without a test) |
| performance | `engagement-scenario-performance` | `measure_after_days` after the start |
| recheck | `engagement-repeat-purchase-cohorts` | `recheck_after_days` after the start |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the coverage map, reads the launcher's and the A/B test setup's plan and verify files into the change log, records the builder's writes and the day the flow started, and prints what's next and when. See [examples/first-time-buyers.md](examples/first-time-buyers.md).

## Notes and limitations

- The baseline comes first so the adapt stage can set the waits from it: the cohorts skill recommends nudging before the median time to a second order and before the curve drops.
- The adapt stage wasn't in the first sketch of this chain: the launcher never edits its clone, and the waits and the "no second order yet" exit are changes for `engagement-scenario-builder`.
- The recheck compares cohorts whose first order came after the start with the baseline's, month for month. It's a before-and-after comparison, not a test: seasonality and other campaigns move it too. The optional test stage gives a cleaner answer: a holdout added by `engagement-ab-test-setup` and read out by `engagement-experiment-readout`. Skip the test stage and `status` offers the ab-read-out stage as a skip.
- If both flows are already live, the run stops at the find stage: the builder never edits a running flow.
- The find stage's money is an estimate under `lifecycle-coverage-map`'s stated assumptions.
