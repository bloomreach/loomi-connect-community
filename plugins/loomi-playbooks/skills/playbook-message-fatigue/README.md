# Playbook: message fatigue

Takes one Bloomreach Engagement project from "customers get too many messages" to "the flow that piles them on is thinned, and here is what opt-outs and revenue did since", by running existing skills in order: measure how many messages customers get and where opt-outs climb, find the flows and campaigns that stack sends on the same people, add a wait, a frequency or consent condition or a limit to the chosen flow (or test the cut first with a holdout or timing split), QA it, and once you have switched it on, read any test out, measure frequency and opt-outs again and check clicks and revenue held. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `engagement-scenario-builder` changes a draft or stopped flow, or makes a new draft copy of a running one; `engagement-ab-test-setup`, if you want to test the cut, adds an A/B split to a draft or stopped flow (or, for a running flow, makes a new draft copy with it). Each write only after its own explicit "yes". The playbook never switches a flow on or off, changes a one-off campaign or sets a frequency policy: you do those in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_scenario`, `update_scenario`, `update_scenario_node` |
| **Other requirements** | The `loomi-engagement` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our unsubscribes keep climbing and people say we email too much. Find out which flows do it and fix it."
- "Are we over-messaging anyone? If so, cut it back where it comes from."
- "Carry on with the message-fatigue run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| measure | `contact-frequency-audit` | now |
| sources | `engagement-send-collision-check` | now |
| cut | `engagement-scenario-builder` | now, after confirmations |
| test | `engagement-ab-test-setup` | now, after its confirmation (only if you test the cut instead) |
| qa | `scenario-qa` | now; done when you switch the flow on |
| ab-read-out | `engagement-experiment-readout` | `readout_after_days` after the start (skipped without a test) |
| recheck | `contact-frequency-audit` | `recheck_after_days` after the change |
| impact | `change-impact-tracker` | `recheck_after_days` after the change (skipped when a test ran) |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the first two stages, records the builder's writes, reads the A/B test setup's plan and verify files into the change log, records the day you switched the flow on (and stopped the original, for a copy) or changed campaigns in the app, and prints what's next and when. See [examples/stacked-flows.md](examples/stacked-flows.md).

## How it differs from deliverability recovery

[playbook-deliverability-recovery](../playbook-deliverability-recovery/) starts from inbox health: bounces, spam complaints and a slipping deliverability trend, and it adds a **new** sunset or re-permission flow for unengaged addresses, then trends deliverability again. This playbook starts from **volume per customer**: opt-outs that rise with how many messages people get. It finds the existing flows and campaigns that stack sends on the same customers, sends fewer of them, and checks opt-outs by frequency level and revenue afterwards. Both run `contact-frequency-audit`; if bounces or the complaint trend are the problem, use deliverability recovery.

## Notes and limitations

- **One-off campaigns are out of scope for writes.** No stage skill changes, reschedules or cancels a standalone campaign, or writes a frequency policy. When the excess is in campaigns, you make the change the collision check suggests in the Engagement UI, the run records it, and goes straight to the recheck and impact stages.
- A running flow can't be edited: the builder (or the A/B setup) makes a new draft copy, and you switch the copy on and stop the original in the Engagement UI. A copy's frequency policy is set to `Default`, not the project's own default, and its email steps' identity transfer is off: compare both with the original before switching it on.
- The A/B test covers a holdout (skip the extra message) or a timing test (a longer wait). A frequency or consent condition can't be the variant, because `engagement-ab-test-setup` builds only the split and a copy of a step.
- `engagement-send-collision-check` reads the campaign calendar and the always-on flows; it doesn't count delivered messages per flow. For a candidate flow's own sends and unsubscribes, run `engagement-scenario-performance` on it in the sources stage.
- The recheck is project-wide and before and after: one flow's cut can move it only a little, and a new cap or a big campaign in the same weeks moves it too; the summary names them. `change-impact-tracker` is observational as well. Only the A/B read-out is a controlled answer.
