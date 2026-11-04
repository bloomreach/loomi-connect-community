# Change file format

`scripts/algorithm_fix_plan.py plan --changes <file>` reads a JSON list of the ranking algorithm changes to plan. Write it with your file-writing tool, from the user's request or a `discovery-ranking-algorithm-review` finding. One object per change, one change per algorithm:

| Field | For | Meaning |
|---|---|---|
| `action` | all | `update`, `create` or `delete` |
| `algorithm_id` | update, delete | The algorithm's numeric `id` from `search_ranking_algorithms` (not the `br-…` `algoId`) |
| `copy_of` | create | The numeric `id` of the algorithm to copy. A legacy algorithm is copied as `MANUAL` (`create_ranking_algorithm`); an ABR model as `ABR_MANUAL` (`create_abr_algorithm`, with the source as `base_algo_id`). Same catalog and page type |
| `name` | create (required); update | The new name. No other algorithm of the same page type may have it |
| `description` | optional | The new description |
| `weights` | update; create (optional) | `{signal: new weight}` for the top-level (combined) signals to change, each from `weight_min` to `weight_max` in references/rules.json |
| `rebalance` | optional | `true` scales the signals you didn't name so the weights still add up to `weight_total`. Without it, the new weights must already add up to it (within `weight_sum_tolerance`) |
| `skip_test` | optional | `true` only when the user, told that a busy algorithm should be A/B tested first, chooses to change it in place anyway |
| `reason` | optional | Why: the finding it fixes. Shown in the plan |

Example:

```json
[
  {"action": "update", "algorithm_id": 11, "weights": {"raw_qd_revenue_keyword": 30}, "rebalance": true,
   "reason": "Review: revenue weighted low"},
  {"action": "create", "copy_of": 21, "name": "Margin cat v2", "weights": {"margin": 10}, "rebalance": true,
   "reason": "Review: custom signal margin drives the order; test a lower weight"},
  {"action": "update", "algorithm_id": 13, "name": "Summer boost (old)", "reason": "Review: same name"},
  {"action": "delete", "algorithm_id": 12, "reason": "Review: not seen in use, near-duplicate of 13"}
]
```

## Weights

- Legacy algorithms keep weights in `modelMetaData.combined` (one entry per signal: `weight`, `min`, `max`, `featureType`), shares of 100. `modelMetaData.text` holds the text-matching signals that make up `text_score`; this skill doesn't change them. The update and the undo send the whole `modelMetaData` back, with only the changed weights rewritten.
- ABR models keep a `weights` list (`feature_key`, `display_weight`). The plan applies the same range and total; Discovery has the final say.
- `min` and `max` are the signal's range in the catalog. For a margin or cost-type signal (`sensitive_signal_words`) they are commercial values: the script hides them in what it prints, and they're never shown to the user.
- Signals can't be added or removed here; a different set of signals is a new algorithm, built in Ranking Studio.

## What the plan checks

| Check | Result |
|---|---|
| weight not a number, outside the range, or total off | blocked |
| signal not in the algorithm, or a text-matching signal | blocked |
| trained ABR model (`trained_abr_types`) given weights | blocked: `update_ranking_algorithm` would make it `ABR_MANUAL` for good. Copy it instead |
| classic or non-linear ranker given weights | blocked: no editable weights |
| weight change on the Default, or on an algorithm whose sampled pages had `high_traffic_visits` or more | blocked unless `skip_test`: copy and A/B test it |
| weight change or delete with no usage check (no review with sampled pages, no grids) | blocked |
| weight change or delete of an algorithm a running test's bucket rule uses, or while a running test's bucket rule wasn't read | blocked |
| delete of an algorithm seen in use (review, grids, rules), the Default, or one of `protected_types` | blocked |
| create at `max_custom_per_catalog` custom algorithms for the catalog and page type | blocked |
| name already used on the same page type | blocked |
| change touching a margin or cost-type signal | warning |
| hand-set weights on a trained `ML_*` model | warning |

## Undo

| Change | Undo |
|---|---|
| update | `update_ranking_algorithm` with the saved name, description and whole `modelMetaData` or `weights` (legacy weights re-sync again, about 20 minutes) |
| create | `delete_ranking_algorithm` on the new ID (known after the create) |
| delete, legacy | `create_ranking_algorithm` as `MANUAL` with the saved `modelMetaData`: same weights, new ID. A trained type comes back as `MANUAL` |
| delete, `ABR_MANUAL` with a `baseAlgoId` | `create_abr_algorithm` as `ABR_MANUAL` with the saved weights |
| delete, other ABR | none: `undo_note` says to recreate it in Ranking Studio from the saved `definition` (it retrains) |

A deleted algorithm comes back with a new ID and `algoId`. Nothing pointed at the old one (the plan blocks deleting one in use), so nothing needs repointing.
