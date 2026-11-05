# Playbook: revenue drop

An incident runbook for a drop in revenue, conversion or order value. It explains the drop and ranks its causes, then checks only the suspects the explanation hasn't ruled out: tracking and feeds, the search API, live Engagement flows and a recent merchandising change. If a rule made it worse, it rolls it back from a fresh read and its own plan, and after a wait checks that revenue recovered. A hand-off file in your working folder carries the findings, the changes and the dates between stages.

| | |
|---|---|
| **Products** | Discovery and Engagement (Engagement optional: without it, the journeys stage is skipped) |
| **Access** | **Writes**, through its stage skills only: `discovery-rule-cleanup` switches off (or sets an end date on) the rule that made the drop worse, live at once, staging first and production on a separate yes, each batch only after its own explicit "yes". This playbook never deletes: if the cleanup skill proposes a delete, it stops, and the delete is a separate job for `discovery-rule-cleanup` outside the run, with its own yes |
| **Loomi Connect tools** | Those of its stage skills. Writes: `update_ranking_rule`, `update_facet_rule` |
| **Other requirements** | The `loomi-platform`, `loomi-discovery` and `loomi-engagement` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Revenue dropped 20% last week. Find out why and fix it."
- "Conversion fell off a cliff on Tuesday. Run the incident checks."
- "Carry on with the revenue drop run: has it recovered since we switched the rule off?" (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| explain | `revenue-anomaly-explainer` | now |
| feeds | `data-feed-health` | now, unless the explainer ruled it out |
| api | `discovery-api-health` | now, unless ruled out |
| journeys | `engagement-journey-health` | now, unless ruled out |
| change | `change-impact-tracker` | now, when a rule or test changed in the window |
| rollback | `discovery-rule-cleanup` | now, after confirmations, when a rule made it worse |
| recovery | `revenue-anomaly-explainer` | `recovery_check_days` after the rollback (or the date another fix landed) |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records each candidate cause as a finding, reads the cleanup skill's production plan and verify files into the change log, and prints what's next and when. See [examples/tuesday-drop.md](examples/tuesday-drop.md).

## Notes and limitations

- Checks the explainer already ruled out are recorded `ruled_out`, so the hand-off file says why they weren't run. A drop within normal variation skips the rest of the run.
- `revenue-anomaly-explainer` reads Discovery data; the Engagement side is covered by the journeys stage only.
- Only rules are rolled back here. `discovery-rule-cleanup` doesn't switch a rule on, or write banners or redirects; feed, API and flow fixes are made by their owners, and their fix date sets the recovery check.
- A recent change measured by `change-impact-tracker` is often `too_early_to_tell` in an incident. The rollback decision then rests on weaker evidence and the cleanup skill's own impact check; say so.
- The change log holds only the production pass: `handoff.py` refuses a plan for another environment than the run's.
