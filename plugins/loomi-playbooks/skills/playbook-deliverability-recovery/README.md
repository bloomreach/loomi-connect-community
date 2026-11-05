# Playbook: deliverability recovery

Takes one Bloomreach Engagement project from "complaints and bounces are rising" to "a sunset or re-permission flow is live, and here is what deliverability did since", by running existing skills in order: trend deliverability and find where problems come from, measure over-messaging and reachability, clone a sunset or re-permission flow as a draft, build or fix it, QA it, and once you have switched it on, trend deliverability again. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `scenario-template-launcher` clones one scenario as a draft that never starts; `engagement-scenario-builder` creates or changes a draft scenario. Each write only after its own explicit "yes". The playbook never switches a flow on, sets a cap or changes consent: you do those in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `clone_scenario`, `create_scenario`, `update_scenario`, `update_scenario_node` |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our spam complaints keep creeping up. Find out why and fix it."
- "We need a sunset flow before Black Friday: check deliverability first, then set it up."
- "Carry on with the deliverability run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| trend | `deliverability-trend` | now |
| frequency | `contact-frequency-audit` | now |
| reach | `contactability-audit` | now |
| launch | `scenario-template-launcher` | now, after its confirmation |
| adapt | `engagement-scenario-builder` | now, after confirmations |
| qa | `scenario-qa` | now; done when you switch the flow on |
| recheck | `deliverability-trend` | `recheck_after_days` after the start |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the first three stages, reads the launcher's plan and verify files into the change log, records the builder's writes and the day the flow started, and prints what's next and when. See [examples/complaint-drift.md](examples/complaint-drift.md).

## Notes and limitations

- The recheck is before and after, not a controlled test: a cap or a big send in the same weeks moves the rates too, and the summary names them.
- Frequency caps, suppression and consent changes are yours to make in Engagement: no skill writes them. Mark the finding done when you have, so the recheck can name it.
- The adapt and qa stages weren't in the first sketch of this chain: the launcher never edits its clone and hands every clone to `scenario-qa`, and the flow must be switched on before the recheck means anything.
- When the reach stage finds nothing a flow would fix, `status` suggests skipping the rest, so a cap-only fix isn't rechecked by this playbook: run `deliverability-trend` again yourself.
