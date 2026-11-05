# Playbook: monthly hygiene

One monthly sweep across a Discovery account and an Engagement project, by running six existing skills in three pairs: audit the merchandising rules and clean up the approved ones, audit the search redirects and fix the approved ones, then list the Engagement project's stale drafts, test copies and unused definitions and map what depends on them into a safe deletion order you act on in the Engagement UI. Each write stage builds one plan for you to review; each batch, delete and switch-on still needs its own "yes". A hand-off file in your working folder holds the findings and the change log, so a sweep can stop and continue later, and each month's file shows what was cleaned.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | **Writes**, through its stage skills only: `discovery-rule-cleanup` disables, re-dates, retargets and deletes ranking and facet rules; `discovery-redirect-fixer` creates, switches on, changes and deletes redirects. Each write only after its own explicit "yes", each delete on its own. Nothing in Engagement is written |
| **Loomi Connect tools** | Those of its stage skills. Writes: `update_ranking_rule`, `delete_ranking_rule`, `update_facet_rule`, `delete_facet_rule`, `create_redirect`, `update_redirect`, `delete_redirect` |
| **Other requirements** | The `loomi-discovery` and `loomi-engagement` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "It's the start of the month: run the hygiene sweep."
- "Tidy up our Discovery rules and redirects, and tell me what's safe to delete in Engagement."
- "Carry on with this month's hygiene sweep, but skip the redirects." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| rule-audit | `discovery-rule-audit` | now |
| rule-cleanup | `discovery-rule-cleanup` | now, after confirmations |
| redirect-audit | `discovery-redirect-audit` | now |
| redirect-fix | `discovery-redirect-fixer` | now, after confirmations |
| asset-cleanup | `engagement-asset-cleanup` | now |
| dependency-map | `engagement-dependency-map` | now |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from each audit, reads the write skills' plan and verify files into the change log, and lists every month's changes with `list --changes`. See [examples/november-sweep.md](examples/november-sweep.md).

## Notes and limitations

- Nothing in Engagement is deleted or archived: there's no skill for it, and the dependency map gives the order for a person to follow in the UI.
- Media rules (banners) have no write tool; the rule audit's media findings come with dashboard steps.
- A run can cover Discovery, Engagement or both; with one product, the other product's stages are offered as skips.
- One plan per write stage covers many findings, so the change log ties changes to the run rather than to each finding.
