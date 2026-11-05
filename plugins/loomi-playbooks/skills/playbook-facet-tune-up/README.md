# Playbook: facet tune-up

Takes one Bloomreach Discovery account's filters (facets) from "shoppers can't narrow down the results" to "the right filters show first, and here's whether it helped", by running four existing skills in order: review the filters on the top searches and categories, check each chosen change before anything is written, make it by updating the facet rule that covers the page (or adding one switched off), and measure the busiest change after it has run. Value merges, renames and price ranges, which Loomi Connect can't set, are listed as dashboard steps. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `facet-rule-fixer` updates the facet rule that covers a page (live at once if the rule is on), creates a new rule switched off and switches it on, and can switch one off. Each write only after its own explicit "yes". This playbook never deletes: if the fixer proposes a delete, it stops, and the delete is a separate job for `facet-rule-fixer` outside the run, with its own yes |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_facet_rule`, `update_facet_rule` |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our filters are a mess. Review them and fix the worst ones."
- "Show size first on jeans and hide the internal cluster filter everywhere, and tell me if it helped."
- "Carry on with the facet tune-up run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| review | `facet-optimizer` | now |
| qa | `discovery-change-qa` | now, before anything is written |
| fix | `facet-rule-fixer` | now, after confirmations |
| measure | `change-impact-tracker` | `measure_after_days` after the fix |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the review, reads each of the fixer's plan and verify files into the change log, and prints what's next and when. See [examples/apparel-filters.md](examples/apparel-filters.md).

## Notes and limitations

- The qa stage comes before the fixer, not after: the fixer updates the rule that already covers a page, which is live at once if the rule is on, so a check afterwards would look at changes shoppers already see.
- `discovery-change-qa` can't preview a facet change on the grid, and its facet format holds always-shown and hidden facets, not boost or bury positions. It checks scope, contradictions, clashes and running tests; the fixer's plan checks the facet names and positions.
- One finding per rule or page, each with its own plan in the fix stage, so each change stays tied to its finding.
- `change-impact-tracker` measures one change at a time, and a global rule leaves no untouched page as a control. The measure stage takes the busiest search or category rule first.
- Facet changes rarely have a reliable revenue estimate: findings carry sessions affected, not money.
