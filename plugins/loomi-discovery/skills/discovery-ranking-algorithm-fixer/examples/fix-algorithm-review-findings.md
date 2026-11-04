# Example: fixing ranking algorithm review findings

All names, IDs and figures below are invented.

**Prompt:** "The ranking algorithm review for acme_demo flagged a few things. Retire the unused 'Summer boost' duplicate, lower the margin weight on 'Margin cat', and give 'Text relevance' more revenue weight. Staging first."

**Plan (staging),** after reading both algorithm lists, the details of the four algorithms, the review's output, and the experiments (one running test, whose bucket rule was read and uses another algorithm).

'Margin cat' ranks the busiest category pages in the review's sample, so an in-place change is blocked; the plan proposes a corrected copy instead, and the user agrees. Batches: `[1]`, then `[2]`, then `[3]`.

**Change 1: create a corrected copy, 'Margin cat v2'** (category, `MANUAL`, copy of 'Margin cat'). Ranks nothing until tested.

| Signal | Before | After |
|---|---|---|
| margin ⚠ | 30 | 10 |
| raw_qd_revenue_category | 40 | 51.43 |
| raw_qd_views_category | 30 | 38.57 |

Warning: changes a margin or cost-type signal. Undo: `delete_ranking_algorithm` on the new ID.

**Change 2: re-weight 'Text relevance'** (keyword). Live at once on 'dress' and any other page its rule assigns it to; status shows Syncing for about 20 minutes.

| Signal | Before | After |
|---|---|---|
| raw_qd_revenue_keyword | 20 | 30 |
| text_score_keyword | 50 | 43.75 |
| raw_qd_conversions_keyword | 20 | 17.5 |
| raw_qd_views_keyword | 10 | 8.75 |

Undo: `update_ranking_algorithm` with the saved weights.

**Change 3: delete 'Summer boost'** (keyword). Not seen on the review's 5 sampled pages or in the rules given. Undo: recreate as `MANUAL` from the saved definition, with a new ID.

> Make change 1 in staging? It creates an untested copy that ranks nothing yet. (yes / no)

**User:** "yes"

> Change the weights of 'Text relevance' as shown? It ranks 'dress' and the other pages its rules assign, at once. (yes / no)

**User:** "yes"

> Delete 'Summer boost'? It can't be undone, only recreated with a new ID. (delete / skip)

**User:** "delete"

Each write is read back with `search_ranking_algorithms` and checked with `verify`: 1 `in_place` (new ID noted), 2 `in_place` (status Syncing), 3 `gone` (a not-found naming its ID).

## Ranking algorithm changes: acme_demo, staging (2026-11-04)

| # | Change | Algorithm | Result | Status | Undo |
|---|---|---|---|---|---|
| 1 | create copy | Margin cat v2 (category) | done | Available | delete_ranking_algorithm on the new ID |
| 2 | weights | Text relevance (keyword) | done | Syncing | update_ranking_algorithm with the saved weights |
| 3 | delete | Summer boost (keyword) | done | gone | create_ranking_algorithm (MANUAL) from the saved definition |

**Not changed:** in-place change to 'Margin cat' (busy pages; replaced by the copy).
**Undo plan:** plan-staging.json
**Next:** `discovery-experiment-setup` to A/B test 'Margin cat v2' against 'Margin cat' on the top category pages; then the production plan.
