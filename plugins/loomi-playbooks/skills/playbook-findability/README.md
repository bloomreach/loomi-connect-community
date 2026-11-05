# Playbook: findability

Gets products found for the words shoppers use, by running five existing skills in order: triage the dead-end searches, audit the product data behind them, write title and attribute suggestions for the feed team, check those attributes are searchable, add the synonyms the triage found, and triage again a few weeks later to count the searches that recovered. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-synonym-fixer` creates synonyms switched off, switches them on (live after the next sync) and can change or switch one off. Each write only after its own explicit "yes". This playbook never deletes: if the fixer proposes a delete, it stops, and the delete is a separate job for `discovery-synonym-fixer` outside the run, with its own yes. Product data and catalog settings are suggestions for people to apply, never written |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_synonym`, `update_synonym` |
| **Other requirements** | The `loomi-discovery` and `loomi-product-data` plugins; a client that can view images for the enhance stage (it falls back to text-only). Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Too many of our searches find nothing. Fix it properly, not just with synonyms."
- "Make our products findable for the words shoppers actually type."
- "Carry on with the findability run: has the recheck come round?" (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| triage | `discovery-zero-results-triage` | now |
| audit | `product-data-audit` | now |
| enhance | `product-data-enhancer` | now |
| config | `discovery-catalog-config-audit` | now |
| synonyms | `discovery-synonym-fixer` | now, after confirmations |
| recheck | `discovery-zero-results-triage` | `recheck_after_days` after the synonyms |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from each stage's result, reads the synonym fixer's plan and verify files into the change log, and prints what's next and when. See [examples/dead-end-searches.md](examples/dead-end-searches.md).

## Notes and limitations

- Product data suggestions and catalog settings are made by people (the feed team, the dashboard), outside the change log, so the recheck can't tell which fix recovered a search when several landed in the window.
- Redirect candidates and blocking rules become findings for `discovery-redirect-fixer` and `discovery-rule-cleanup`; this playbook doesn't run them.
- The enhance stage runs up to its skill's batch size per session; larger lists take several sessions.
- The recheck counts recovered searches; for a measured effect of one synonym, use `change-impact-tracker`.
