# Playbook: synonym tune-up

Takes one Bloomreach Discovery account's synonyms from "nobody knows what these do" to "the bad ones are gone, the right ones fire, and here's whether it helped", by running three existing skills in order: review the user-created and Bloomreach-generated synonyms and what actually fires on the top searches, fix the bad, risky, no-op and leftover test ones and add missing wordings (each previewed before it's written), and measure the busiest change after it has run. Bloomreach-generated synonyms, which Loomi Connect can't change, are listed for you to disable in the dashboard. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-synonym-fixer` creates synonyms switched off and switches them on, changes their terms or direction, switches them off, and deletes User Created ones the review flagged as no-op or test data. Each write only after its own explicit "yes", with a separate yes for every switch-on and every delete. It never reverts a User Modified synonym (that re-enables the Bloomreach-generated one): if the fixer proposes one, it stops, and the revert is a separate job outside the run |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_synonym`, `update_synonym`, `delete_synonym` |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our synonyms are a mess. Review them and clean up the bad ones."
- "Get rid of the test synonyms someone left behind, and fix the one that sends 'swim' to bikinis."
- "Carry on with the synonym tune-up run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| review | `discovery-synonym-review` | now |
| fix | `discovery-synonym-fixer` (previews with `discovery-change-qa`) | now, after confirmations |
| measure | `change-impact-tracker` | `measure_after_days` after the fix |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the review, reads the fixer's plan and verify files into the change log, records the dashboard disables you make, and prints what's next and when. See [examples/swimwear-synonyms.md](examples/swimwear-synonyms.md).

## How this differs from playbook-findability

[playbook-findability](../playbook-findability/) starts from dead-end searches and only **adds** synonyms for them, alongside product data and catalog fixes. This playbook starts from the synonyms the account **already has**, and mostly switches off, narrows or removes them; it adds a synonym only where the review finds a missing wording on a busy query.

## Notes and limitations

- There's no separate QA stage, unlike [playbook-facet-tune-up](../playbook-facet-tune-up/): `discovery-synonym-fixer` runs `discovery-change-qa` itself on the exact change files its plan writes, before writing. `discovery-change-qa` can preview a synonym that adds or changes an expansion, but not a switch-off or delete; for those, the review's grid test is the evidence.
- Bloomreach-generated synonyms can't be changed with Loomi Connect. You disable them in the dashboard and tell the playbook, which records the change (source `discovery-ui`) so the measure stage and quarter-close see it.
- Deletes are allowed only for User Created no-op or test synonyms, each on its own yes; switching off is preferred. A revert of a User Modified synonym is never part of the run.
- All chosen fixes go in one fixer plan, so its changes belong to the run, not one finding each. The fixer splits the plan into batches.
- `change-impact-tracker` measures one change at a time and checks a change fires before measuring it; for a switch-off, the playbook tells it the expansion was removed, so the check runs the other way round. A run that only removed no-op, test or not-firing synonyms has nothing to measure.
- The review's money is an upper bound for underperforming queries, and null for clean-up.
