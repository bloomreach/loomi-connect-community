# Playbook: revenue drop

An incident runbook for a drop in revenue, conversion or order value, on a Discovery site, in an Engagement project, or both. It explains the drop on each side (the site's traffic, conversion and order value; Engagement purchases as buyers, orders per buyer and order value), reconciles two numbers that disagree, then checks only the suspects the explanations haven't ruled out: tracking and feeds, the search API, live Engagement flows, the purchase funnel and a recent rule, test, campaign or scenario change. If a rule made it worse, it rolls it back from a fresh read and its own plan; if a campaign or scenario did, you stop it in Engagement and the run records it. After a wait it checks that revenue recovered. A hand-off file in your working folder carries the findings, the changes and the dates between stages.

| | |
|---|---|
| **Products** | Discovery, Engagement, or both: a run with one product is offered the other product's stages as skips |
| **Access** | **Writes** (Discovery only), through its stage skills only: `discovery-rule-cleanup` switches off (or sets an end date on) the rule that made the drop worse, live at once, staging first and production on a separate yes, each batch only after its own explicit "yes". This playbook never deletes: if the cleanup skill proposes a delete, it stops, and the delete is a separate job for `discovery-rule-cleanup` outside the run, with its own yes. Every Engagement stage is read-only, and it never stops a campaign or scenario: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `update_ranking_rule`, `update_facet_rule` |
| **Other requirements** | The `loomi-platform`, `loomi-discovery` and `loomi-engagement` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Revenue dropped 20% last week. Find out why and fix it."
- "Conversion fell off a cliff on Tuesday. Run the incident checks."
- "Our email revenue is down 15% month on month, but the BI dashboard says 25%. What happened?"
- "Carry on with the revenue drop run: has it recovered since we switched the rule off?" (with its hand-off file)

## How it works

| Stage | Skill | Product | When |
|---|---|---|---|
| explain | `revenue-anomaly-explainer` | Discovery | now |
| engagement-explain | `engagement-revenue-change-explainer` | Engagement | now |
| numbers | `engagement-number-reconciliation` | Engagement | now, only when two numbers disagree |
| feeds | `data-feed-health` | both | now, unless the explainers ruled it out |
| api | `discovery-api-health` | Discovery | now, unless ruled out |
| journeys | `engagement-journey-health` | Engagement | now, unless ruled out |
| funnel | `funnel-leak-finder` | Engagement | now, unless ruled out |
| change | `change-impact-tracker` | both | now, when a rule, test, campaign or scenario changed in the window |
| rollback | `discovery-rule-cleanup` | Discovery | now, after confirmations, when a rule made it worse |
| recovery | `revenue-anomaly-explainer` | Discovery | `recovery_check_days` after the rollback (or the date another fix landed) |
| engagement-recovery | `engagement-revenue-change-explainer` | Engagement | the same |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records each candidate cause as a finding, offers the stages of a product the run doesn't have as skips, reads the cleanup skill's production plan and verify files into the change log, and prints what's next and when. See [examples/tuesday-drop.md](examples/tuesday-drop.md).

## Notes and limitations

- Checks the explainers already ruled out are recorded `ruled_out`, so the hand-off file says why they weren't run. When neither explainer finds a drop beyond normal variation, or the numbers stage finds the gap is a difference in definitions, the rest of the run is offered as a skip.
- `revenue-anomaly-explainer` reads Discovery data and `engagement-revenue-change-explainer` reads Engagement purchase events; with both products, both run, and the numbers stage settles which number to trust when they disagree.
- Only Discovery rules are rolled back here. A campaign or scenario that made it worse is paused or stopped by you in the Engagement UI, and recorded in the change log so the recovery check and `playbook-quarter-close` see it. `discovery-rule-cleanup` doesn't switch a rule on, or write banners or redirects; feed, API and flow fixes are made by their owners, and their fix date sets the recovery check.
- A recent change measured by `change-impact-tracker` is often `too_early_to_tell` in an incident. The rollback decision then rests on weaker evidence and the cleanup skill's own impact check; say so.
- The change log holds only the production pass: `handoff.py` refuses a plan for another environment than the run's.
