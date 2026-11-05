# Playbook: fix one search

Takes one Bloomreach Discovery search, such as "black boots", from "why is this bad?" to "the fix is live, and here's whether it helped", by running existing skills in order: diagnose the search, explain a missing or buried product when one is named, check the chosen fix before anything is written, make it as a synonym or a redirect, and measure it after it has run. A ranking fix is handed to `playbook-test-and-learn`, and product data fixes to their own skills. A hand-off file in your working folder carries the findings, the change and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-synonym-fixer` creates a synonym switched off and switches it on (live after the next sync), and can change or switch one off; `discovery-redirect-fixer` does the same for a redirect. Each write only after its own explicit "yes". This playbook never deletes: if a fixer proposes a delete or revert, it stops, and that's a separate job for the fixer outside the run, with its own yes |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_synonym`, `update_synonym`, `create_redirect`, `update_redirect` |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Why is 'black boots' performing so badly? Fix it."
- "Our best-selling Chelsea boot doesn't show for 'black boots'. Why, and can you fix it?"
- "Carry on with the fix-one-search run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| diagnose | `discovery-query-diagnosis` | now |
| visibility | `discovery-product-visibility` | now, only when a product is named |
| qa | `discovery-change-qa` | now, before anything is written |
| synonyms | `discovery-synonym-fixer` | now, after confirmations, when the fix is a synonym |
| redirect | `discovery-redirect-fixer` | now, after confirmations, when the fix is a redirect |
| measure | `change-impact-tracker` | `measure_after_days` after the fix went live |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the diagnosis and the product check, reads the fixer's plan and verify files into the change log, and prints what's next and when. See [examples/black-boots.md](examples/black-boots.md).

## Notes and limitations

- One fix per run, so the measure stage can tell what helped. Start a new hand-off file for another fix to the same search.
- The qa stage comes before the fixers, not after: both fixers switch a new item on in the same run, and a change to an existing synonym or redirect is live at once, so a check afterwards would look at a change shoppers already see. Each fixer's own preview then checks the exact change its plan wrote.
- Ranking fixes aren't made here: `playbook-test-and-learn` tests a fixed variant of a rule that already ranks the query, and `discovery-experiment-setup` tests a new rule. Product data fixes go to `product-data-enhancer`, and products missing from the index to `data-feed-health`.
- The diagnosis's money is an upper bound for the period, not a forecast. Only the measure stage measures.
- The measure stage's wait counts from the day the fix went live, which the synonyms or redirect stage records (`--not-before`): the script can't count from "whichever of two stages ran".
