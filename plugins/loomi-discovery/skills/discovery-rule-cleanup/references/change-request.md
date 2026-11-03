# Change request and plan rules

## Change request format

A JSON list, or `{"changes": [...]}`. One entry per rule:

```json
{"changes": [
  {"rule_id": 2001, "action": "disable", "priority": "high", "reason": "Expired but still enabled"},
  {"rule_id": 2002, "action": "delete", "priority": "low", "reason": "Disabled and expired"},
  {"rule_id": 2007, "action": "set_end_date", "end_date": "2026-12-31", "priority": "medium", "reason": "Seasonal, no end date"},
  {"rule_id": 2009, "action": "set_queries", "priority": "medium", "reason": "Shoppers type 'backpacks'",
   "queries": [{"query": "backpacks", "queryType": "sitesearch", "matchType": "EXACT_MATCH"}]}
]}
```

| Field | Meaning |
|---|---|
| `rule_id` | The rule's numeric ID |
| `action` | `disable`, `delete`, `set_end_date` or `set_queries`. Nothing else: switching rules on, or other edits, go through `discovery-change-qa` and the dashboard |
| `end_date` | For `set_end_date`: `YYYY-MM-DD`. The rule ends at 23:59:59 UTC that day |
| `queries` | For `set_queries`: the full new list. `matchType` defaults to `EXACT_MATCH` |
| `priority` | `high`, `medium` or `low` (from the audit). Higher priorities go first in a batch |
| `reason` | Why, in a few words: shown in the plan |
| `owner_confirmed` | `true` only when the owner of a protected rule (name like "do not delete") has agreed |

## What the plan does with each request

The plan uses the shared shape in the repo's authoring guide ("Plan files for write skills"). "Blocked" below means `status: blocked`, with the reason in `problems`.

| Request | Plan |
|---|---|
| Media rule (`ruleType: campaign`) | Blocked: no write tool. Give the dashboard steps |
| Redirect | Blocked: `discovery-redirect-fixer` |
| Rule in a running test (`isLive`, `isAbTestLive`, or a bucket of an experiment whose status is in `running_statuses`, compared case-insensitively, or missing) | Blocked until the test ends |
| `isEditable: false` | Blocked |
| Name matches `protected_name_pattern` | Blocked unless `owner_confirmed: true` |
| `disable` on a disabled rule | `no_change` |
| `delete` on an enabled rule | Planned as a **disable**: delete it later |
| `delete` on a disabled rule that's expired, or last changed `delete_min_disabled_days` ago or more | A delete in a batch of its own, with an empty undo |
| `delete` on a rule disabled more recently | Blocked for now |
| `set_end_date` in the past | Blocked: disable instead |
| `set_end_date` on a rule with no end date | Planned, but the undo is "clear it in the dashboard" |
| `set_queries` when the saved rule has no `matchType` | Blocked: save the detail, not the list |
| More than `max_changes_per_batch` ready changes | Further batches. Only ready changes count; each delete is a batch of its own |

## The write tools (checked against their published schemas, 2026-11)

- `update_ranking_rule` and `update_facet_rule` fetch the stored rule and merge the fields you send: anything you leave out is kept, including audiences. `null` means "keep", so an end date can't be cleared this way.
- Both take `rule_id`, `environment` (`production` or `staging`), `account_name`, `site_group_id`, and the changed fields: `enabled`, `ended_at` (ms), `started_at` (ms), `queries` (replaces the list).
- `delete_ranking_rule` and `delete_facet_rule` are permanent. They fail with 400 "Customization is live" while the rule is in a running test.
- There's no update or delete tool for media rules.
