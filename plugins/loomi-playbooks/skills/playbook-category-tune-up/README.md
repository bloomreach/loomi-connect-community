# Playbook: category tune-up

Takes one Bloomreach Discovery account's category pages from "which categories underperform, and what's missing?" to "the fixes and new collections are in place, and here's whether they helped", by running five existing skills in order: check category pages against like-for-like peers, review every dynamic category, suggest new collections, build the chosen one in depth, and measure the change you made in the dashboard. No Loomi Connect tool creates dynamic categories, so you make the definitions in the Discovery dashboard; ranking fixes are handed to `playbook-test-and-learn`. A hand-off file in your working folder carries the findings, your changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of its stage skills (all read tools) |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Give our category pages a tune-up: what's underperforming, which dynamic categories are broken, and what collections are we missing?"
- "Our sale collection looks empty. Check every dynamic category and suggest what to add."
- "I've made the new collection in the dashboard. Carry on with the category tune-up run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| health | `discovery-category-health` | now |
| dynamic | `discovery-dynamic-category-review` | now |
| suggest | `collection-suggester` | now |
| build | `topic-collection-builder` | now |
| measure | `change-impact-tracker` | `measure_after_days` after your change went live |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from each stage, records the changes you made in the dashboard, and prints what's next and when. See [examples/missing-collection.md](examples/missing-collection.md).

## Notes and limitations

- Every stage skill is read-only, and no Loomi Connect tool creates or edits Discovery dynamic categories (`create_item_collection` makes a Data Hub product-data collection, not a merchandising one). You make the definitions and fixes in the dashboard; the run records them so the measure stage and `playbook-quarter-close` see them.
- Ranking fixes from the health stage (buried products, a weak first screen) are tested before they're kept: take them to `playbook-test-and-learn`, or `discovery-experiment-setup` for a new rule. Facet problems go to `playbook-facet-tune-up`.
- `collection-suggester` suggests several collections; `topic-collection-builder` builds one in depth. Run the build stage again in a new hand-off file for another.
- The measure stage's wait counts from the day your change went live, which you report: the script's own floor counts from the health stage.
- Money from the health and dynamic stages is an upper bound for the period, not a forecast. Only the measure stage measures.
