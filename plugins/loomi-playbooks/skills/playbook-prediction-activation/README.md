# Playbook: prediction activation

Takes one Bloomreach Engagement prediction from "built but nothing uses it" to "it drives a live flow, and here is what that flow does", by running existing skills in order: find the idle models, build a segment on the chosen model's score band, clone a proven flow as a draft, point it at the segment, optionally add an A/B split to it, QA it, and once you have switched it on, read the test out, read its results and measure the outcome before and after. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `engagement-segment-builder` creates one customer filter or segmentation; `scenario-template-launcher` clones one scenario as a draft that never starts; `engagement-scenario-builder` creates or changes a draft scenario; `engagement-ab-test-setup`, if you want a test, adds an A/B split to the draft (or, for a running flow, makes a new draft copy with it). Each write only after its own explicit "yes". The playbook never switches a flow on: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_customer_filter`, `create_segmentation`, `clone_scenario`, `create_scenario`, `update_scenario`, `update_scenario_node` |
| **Other requirements** | The `loomi-engagement` and `loomi-platform` plugins, and a role that can view predictions. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "We built a churn model months ago and I don't think anything uses it. Put it to work."
- "Which of our predictions are idle? Activate the best one and tell me if it pays off."
- "Carry on with the prediction-activation run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| check | `prediction-activation-check` | now |
| segment | `engagement-segment-builder` | now, after its confirmation |
| launch | `scenario-template-launcher` | now, after its confirmation |
| adapt | `engagement-scenario-builder` | now, after confirmations |
| test | `engagement-ab-test-setup` | now, after its confirmation (optional) |
| qa | `scenario-qa` | now; done when you switch the flow on |
| ab-read-out | `engagement-experiment-readout` | `readout_after_days` after the start (skipped without a test) |
| performance | `engagement-scenario-performance` | `measure_after_days` after the start |
| impact | `change-impact-tracker` | `measure_after_days` after the start |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the prediction check, records the segment and the builder's writes, reads the launcher's and the A/B test setup's plan and verify files into the change log, records the day the flow started, and prints what's next and when. See [examples/idle-churn-model.md](examples/idle-churn-model.md).

## Notes and limitations

- The adapt, qa and impact stages weren't in the first sketch of this chain. The launcher clones a flow as it is, so pointing it at the new segment is `engagement-scenario-builder`'s job; the flow must pass QA and be switched on before anything is measured; and `engagement-scenario-performance` counts buyers, not revenue.
- The A/B test is optional. A holdout inside the flow, read by `engagement-experiment-readout`, is the controlled answer; the impact stage measures the whole flow before and after, against a control, with or without one. Skip the test stage and `status` offers the ab-read-out stage as a skip.
- Stale or failing models aren't offered for activation: retrain them in Engagement first.
- The segment builder doesn't read back what it creates, so its change stays `unverified`; the qa stage checks the flow uses it.
