# Playbook: lapsed customers

Takes one Bloomreach Engagement project from "how much are lapsed customers costing us?" to "a win-back flow is live for the best group, and here is what it brought back", by running existing skills in order: size the revenue at risk and the groups no flow covers, sharpen the audience with lapsing patterns and trending searches, build the segment, clone a proven win-back flow as a draft, point it at the segment, optionally add a holdout or other A/B split to it, QA it, and once you have switched it on, read the test out, read its results and measure reactivation before and after. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `engagement-segment-builder` creates one customer filter or segmentation; `scenario-template-launcher` clones one scenario as a draft that never starts; `engagement-scenario-builder` creates or changes a draft scenario; `engagement-ab-test-setup`, if you want a test, adds an A/B split to the draft (or, for a running flow, makes a new draft copy with it). Each write only after its own explicit "yes". The playbook never switches a flow on: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_customer_filter`, `create_segmentation`, `clone_scenario`, `create_scenario`, `update_scenario`, `update_scenario_node` |
| **Other requirements** | The `loomi-engagement` and `loomi-platform` plugins; Bloomreach Discovery is optional, for trending searches in the refine stage. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "How much are lapsed customers costing us? Win back the best group and tell me if it worked."
- "Set up a win-back for VIPs who've gone quiet, and measure it."
- "Carry on with the lapsed-customers run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| size | `winback-opportunity` | now |
| refine | `segment-opportunity-finder` | now |
| segment | `engagement-segment-builder` | now, after its confirmation |
| launch | `scenario-template-launcher` | now, after its confirmation |
| adapt | `engagement-scenario-builder` | now, after confirmations |
| test | `engagement-ab-test-setup` | now, after its confirmation (optional) |
| qa | `scenario-qa` | now; done when you switch the flow on |
| ab-read-out | `engagement-experiment-readout` | `readout_after_days` after the start (skipped without a test) |
| performance | `engagement-scenario-performance` | `measure_after_days` after the start |
| impact | `change-impact-tracker` | `measure_after_days` after the start |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the size and refine stages, records the segment and the builder's writes, reads the launcher's and the A/B test setup's plan and verify files into the change log, records the day the flow started, and prints what's next and when. See [examples/quiet-vips.md](examples/quiet-vips.md).

## Notes and limitations

- The adapt and impact stages weren't in the first sketch of this chain. The launcher clones a flow as it is, so pointing it at the new segment is `engagement-scenario-builder`'s job; and `engagement-scenario-performance` counts buyers, not revenue.
- The A/B test is optional. A holdout inside the flow, as `winback-opportunity` recommends, is read by `engagement-experiment-readout` and is the controlled answer; the impact stage measures the whole flow before and after, against a control, with or without one. Skip the test stage and `status` offers the ab-read-out stage as a skip.
- The refine stage reads Discovery search trends itself when you have Discovery (its pattern P5); the run stays an Engagement run.
- Offers and voucher codes are set in Engagement; no stage creates them.
- Audience sizes and money before the impact stage are estimates under the stage skills' stated assumptions.
