# Playbook: lifecycle gap

Takes one Bloomreach Engagement project from "we have no browse abandonment flow" to "the flow is live, sending, and here is what it earns", by running nine existing skills in order: find the missing or weak lifecycle flow, clone a proven scenario for it as a draft, build or fix the draft, optionally add an A/B split to it, QA it, and once you have switched it on, check it is sending, read the test out, read its results and measure the revenue before and after. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `scenario-template-launcher` clones one scenario as a draft that never starts; `engagement-scenario-builder` creates or changes a draft scenario; `engagement-ab-test-setup`, if you want a test, adds an A/B split to the draft (or, for a running flow, makes a new draft copy with it). Each write only after its own explicit "yes". The playbook never switches a flow on: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `clone_scenario`, `create_scenario`, `update_scenario`, `update_scenario_node` |
| **Other requirements** | The `loomi-engagement` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "We have no browse abandonment flow. Get one live and tell me what it makes."
- "Which lifecycle flows are we missing? Fill the biggest gap."
- "Carry on with the lifecycle-gap run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| find | `lifecycle-coverage-map` | now |
| launch | `scenario-template-launcher` | now, after its confirmation |
| adapt | `engagement-scenario-builder` | now, after confirmations |
| test | `engagement-ab-test-setup` | now, after its confirmation (optional) |
| qa | `scenario-qa` | now; done when you switch the flow on |
| health | `engagement-journey-health` | `health_check_days` after the start |
| ab-read-out | `engagement-experiment-readout` | `readout_after_days` after the start (skipped without a test) |
| performance | `engagement-scenario-performance` | `measure_after_days` after the start |
| impact | `change-impact-tracker` | `measure_after_days` after the start |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the coverage map, reads the launcher's plan and verify files into the change log, records the builder's writes, reads the A/B test setup's plan and verify files, records the day the flow started, and prints what's next and when. See [examples/browse-abandonment.md](examples/browse-abandonment.md).

## Notes and limitations

- The A/B test is optional. A holdout inside the flow, read by `engagement-experiment-readout`, is the controlled answer; the impact stage measures the whole flow before and after, against a control, with or without one. Skip the test stage and `status` offers the ab-read-out stage as a skip.
- The adapt stage wasn't in the first sketch of this chain: the launcher never edits its clone, and when there's nothing to clone it hands an outline to `engagement-scenario-builder`.
- The start date is the qa stage's done date. When you switched the flow on before telling the assistant, it backdates the stage with `--today`, the supported way to record a person's action in the app.
- The find stage's money is an estimate under `lifecycle-coverage-map`'s stated assumptions. Only the impact stage measures.
