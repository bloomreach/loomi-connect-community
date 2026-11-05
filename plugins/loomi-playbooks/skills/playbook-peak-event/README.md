# Playbook: peak event

Takes one retail event (Black Friday, a summer sale, a launch) from "what should we run?" through "are we ready?" to "how did it go?". Seven existing skills run in order: plan the campaigns, define the event's landing collections, check site and marketing readiness, check the voucher pools will last, check the event's sends and their collisions shortly before the start, and after the event explain what moved revenue against the period before. A hand-off file in your working folder holds the findings and the event dates, so the run picks up before the sends and again after the event.

| | |
|---|---|
| **Products** | Discovery and Engagement (either one alone: the other's stages are skipped) |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of its stage skills (read tools only) |
| **Other requirements** | The `loomi-platform`, `loomi-discovery` and `loomi-engagement` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Get us ready for Black Friday, 27 November to 1 December."
- "Carry on with the Black Friday run: the sends are scheduled now." (with its hand-off file)
- "Black Friday's over. How did it go against the week before?"

## How it works

| Stage | Skill | When |
|---|---|---|
| plan | `campaign-planner` | weeks before |
| collections | `topic-collection-builder` | weeks before |
| readiness | `peak-readiness-check` | weeks before, and again once blockers are fixed |
| vouchers | `voucher-pool-health` | weeks before |
| preflight | `engagement-send-preflight` | `send_checks_days_before_event` before the start |
| collisions | `engagement-send-collision-check` | with the preflight |
| review | `revenue-anomaly-explainer` | `review_after_event_days` after the end |

At the start, the playbook records the preflight and review dates from the event dates you give (`handoff.py stage --not-before`), so `status` says when to come back. Each problem becomes a finding naming the skill that fixes it. See [examples/black-friday.md](examples/black-friday.md).

## Notes and limitations

- Read-only. Fixes are separate jobs: each finding names the skill that makes it (for example `discovery-rule-cleanup`, `discovery-redirect-fixer`), run outside the playbook under its own confirmations.
- `topic-collection-builder` defines collections; the user creates them in the dashboard. No Loomi Connect tool creates Discovery dynamic categories.
- The review uses Discovery data only (`revenue-anomaly-explainer`); for the event's email and SMS results, run `engagement-campaign-digest`.
- The review compares periods; it isn't a test of what the campaigns caused.
