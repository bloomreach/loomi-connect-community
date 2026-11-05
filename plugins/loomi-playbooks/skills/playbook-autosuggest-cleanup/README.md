# Playbook: autosuggest cleanup

Takes one Bloomreach Discovery account's search-as-you-type suggestions from "autosuggest steers shoppers to junk and dead ends" to "the bad suggestions are gone, and they stay gone", by running two existing skills in order and then the first again: audit what autosuggest offers for the top queries, hide the bad suggestions (and bring back wrongly excluded ones) with exclusion rules created disabled and then switched on, and audit again after a wait. Fixes outside autosuggest, such as synonyms, are handed to their own skills. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-autosuggest-exclusions` creates exclusion rules disabled, switches them on (the suggestions disappear for every shopper), changes their keywords and disables them. Each write only after its own explicit "yes", staging first. This playbook never deletes: if the skill proposes a delete, it stops, and the delete is a separate job for that skill outside the run, with its own yes |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_autosuggest_exclusion_rule`, `update_autosuggest_exclusion_rule` |
| **Other requirements** | The `loomi-discovery` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Autosuggest keeps offering junk. Clean it up."
- "Hide the misspelt and competitor suggestions, and check in a month that they're still gone."
- "Carry on with the autosuggest cleanup run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| audit | `autosuggest-audit` | now |
| exclude | `discovery-autosuggest-exclusions` | now, after confirmations |
| recheck | `autosuggest-audit` | `recheck_after_days` after the exclusions went live |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the audit, reads the exclusions skill's plan and verify files into the change log, and prints what's next and when. See [examples/junk-suggestions.md](examples/junk-suggestions.md).

## Notes and limitations

- There's no qa stage: `discovery-change-qa` doesn't cover autosuggest, and the exclusions skill previews each prefix before and after itself.
- One plan covers every chosen exclusion, so new keywords share rules. The change log ties those changes to the plan, not to single findings.
- An exclusion hides a suggestion; it doesn't fix the query behind it. Weaker wordings and dead ends become findings for `discovery-synonym-fixer` and `discovery-zero-results-triage`, which this playbook doesn't run. Top queries autosuggest never offers have no exclusion fix and stay in the audit report.
- `change-impact-tracker` doesn't measure autosuggest exclusions, so the recheck is a second audit, not a before-and-after estimate.
