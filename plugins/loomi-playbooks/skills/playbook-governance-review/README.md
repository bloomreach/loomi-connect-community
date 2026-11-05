# Playbook: governance review

A quarterly review of the things nobody looks at until an auditor asks: who has access to the Engagement project, which integrations, API triggers, project variables and webhooks it has (and where credentials are stored), how long events are kept against what reads them, the health of the Data Hub collections, the audiences sent to ad platforms and their consent, which Discovery catalog fields reach the storefront, and the Discovery audiences and API parameter overrides behind personalised results. It ends with one findings list, each with an owner. Stages for a product the customer doesn't have are skipped. A hand-off file in your runs folder keeps the findings, so next quarter starts from what is still open.

| | |
|---|---|
| **Products** | Engagement, Discovery (either or both), and Data Hub where the organisation has it |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of its stage skills (`project-access-review`, `integration-inventory`, `data-retention-review`, `datahub-collection-audit`, `ad-audience-sync-health`, `discovery-catalog-config-audit`, `discovery-hidden-config-audit`), all read-only |
| **Other requirements** | The `loomi-engagement`, `loomi-platform` and `loomi-discovery` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "It's the end of the quarter. Run our governance review for the Acme US project and the acme Discovery account."
- "We need SOC 2 evidence: who has access, where are API keys stored, and are our ad audiences consented?"
- "Carry on with the Q4 governance review." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| access | `project-access-review` | now (Engagement) |
| integrations | `integration-inventory` | now (Engagement) |
| retention | `data-retention-review` | now (Engagement) |
| datahub | `datahub-collection-audit` | now, when the organisation has Data Hub |
| ad-audiences | `ad-audience-sync-health` | now (Engagement) |
| catalog-exposure | `discovery-catalog-config-audit` | now (Discovery) |
| hidden-config | `discovery-hidden-config-audit` | now (Discovery) |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from each stage, offers the stages of a product the run doesn't have as skips, and lists last quarter's run so its open findings are checked again. The owner for each stage's findings is in `owners` in [references/rules.json](references/rules.json). See [examples/q4-review.md](examples/q4-review.md).

## Notes and limitations

- It changes nothing. Owners act in the Bloomreach UI, Data Hub or the Discovery dashboard; where a stage names a write skill (`engagement-segment-builder`, `engagement-scenario-builder`), you run it separately, with its own confirmations.
- The access stage's report lists people and is confidential. Findings and the hand-off file count people per project; they never name them.
- Loomi Connect returns no permission levels or last-login dates, no integration enabled state and no ad-platform sync history: the review says so rather than guessing.
- Each finding carries an `owner`: a team or role, never a person, from `owners` in references/rules.json or the one the stage skill names. `status` shows it on each finding.
- The Discovery stages were added to the proposed chain so a review covers both products: `discovery-catalog-config-audit` finds internal fields exposed to the storefront, and `discovery-hidden-config-audit` finds forgotten personalisation audiences and parameter overrides.
- The retention stage is not legal advice.
