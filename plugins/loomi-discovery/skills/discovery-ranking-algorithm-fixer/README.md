# Discovery ranking algorithm fixer

Applies fixes to Bloomreach Discovery ranking algorithms in Ranking Studio, such as the ones `discovery-ranking-algorithm-review` flags: changes signal weights (with the before and after per signal), renames, makes a corrected copy that ranks nothing until it's A/B tested, or retires an unused or duplicate algorithm. It plans each change with the exact tool call and an undo, blocks anything a page or a running A/B test uses, and writes only after an explicit yes.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: changes ranking algorithm weights, names and descriptions (`update_ranking_algorithm`; each live weight change its own yes), creates corrected copies that rank nothing until tested (`create_ranking_algorithm` as `MANUAL`, `create_abr_algorithm` as `ABR_MANUAL` only), and deletes unused algorithms (`delete_ranking_algorithm`), each after you confirm; deletes each need their own yes |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `search_discovery_catalogs`, `search_ranking_algorithms`, `get_ranking_rule`, `search_discovery_experiments`, `search_discovery_product_grid_insights`; writes: `update_ranking_algorithm`, `create_ranking_algorithm`, `create_abr_algorithm`, `delete_ranking_algorithm` |
| **Other requirements** | Python 3 for `scripts/algorithm_fix_plan.py` (standard library only) |
| **Tested with** | Claude Code (plan script on synthetic data; reads and response shapes checked on a demo account; no live writes) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Act on the ranking algorithm review: retire the unused duplicate 'Summer boost'"
- "Lower the margin weight on our category algorithm"
- "Make a copy of 'Text relevance' with more weight on revenue, so we can test it"

## Example output

See [examples/fix-algorithm-review-findings.md](examples/fix-algorithm-review-findings.md).

## Notes and limitations

- Weight changes go live at once on every page the algorithm ranks; legacy weights re-sync, showing `Syncing` for about 20 minutes. For the default or a busy algorithm, the skill proposes a corrected copy and an A/B test (`discovery-experiment-setup`) rather than an in-place change.
- It never assigns an algorithm to a page (`ranking_algo` rules), never retrains, and never creates trained ABR models.
- "Not in use" comes from the review's sample of top pages and any rules given; Discovery also refuses to delete an algorithm a rule still uses.
- Passing weights to a trained ABR model would turn it into `ABR_MANUAL` for good, so the skill copies it instead.
- Margin, cost and custom signals: changes are flagged, and no signal's `min` or `max` is printed. They stay in the plan file, and the write call itself carries them to Discovery (with the undo), so they do pass through the assistant's tool call, though never into its replies.
- Deletes are permanent: the undo recreates the algorithm from the saved definition with a new ID, and trained ABR models can only be rebuilt in Ranking Studio.
- The write payloads follow the tools' published schemas; they haven't been run against a live account while building the skill. ABR weights were checked against the tool's example only, as the demo account has no ABR models.
