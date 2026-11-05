# Playbook: search vs category

Makes searches for category names ("dresses", "mens pants") land as well as browsing, by running three existing skills in order: compare each busy category-name search with its category page, redirect the chosen one to the category with an exact-match redirect, and check after it has run that the redirect helped. Searches that need a ranking change instead are handed to `playbook-test-and-learn`. A hand-off file in your working folder carries the findings, the change and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**, through its stage skills only: `discovery-redirect-fixer` creates a redirect switched off, switches it on (live for shoppers) and can change or delete one. Each write only after its own explicit "yes" |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_redirect`, `update_redirect`, `delete_redirect` |
| **Other requirements** | The `loomi-discovery` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Do searches for our category names land as well as the category pages? Redirect the worst one."
- "Should 'dresses' go straight to the dresses category? Set it up and check it worked."
- "Carry on with the search-vs-category run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| match | `discovery-search-category-match` | now |
| fix | `discovery-redirect-fixer` | now, after confirmations |
| measure | `change-impact-tracker` | `measure_after_days` after the fix |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the match result, reads the redirect fixer's plan and verify files into the change log, and prints what's next and when. See [examples/category-redirect.md](examples/category-redirect.md).

## Notes and limitations

- One redirect per run, so the measure stage can tell what helped. Start a new hand-off file for the next one.
- Queries that match several categories are never redirected: the match skill reports them separately.
- `align_ranking` findings need a ranking change, which this playbook doesn't make: take them to `playbook-test-and-learn`.
- The match skill gives no money estimate, so findings carry sessions and conversion, not revenue at stake.
