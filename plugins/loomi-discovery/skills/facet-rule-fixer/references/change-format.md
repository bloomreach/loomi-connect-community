# Change file and plan rules

## Change file format

`scripts/facet_rule_plan.py plan --changes <file>` reads a JSON list of changes, or `{"changes": [...]}`. Write it from the user's request or from `facet-optimizer`'s recommendations, one object per rule or target. Only include what the user asked for or agreed to.

| Field | For | Meaning |
|---|---|---|
| `action` | all | `set` (find the rule for a target and change it, or create one), `update` (a rule by `rule_id`), `enable`, `disable` or `delete` |
| `scope` | `set` | `global` (every search and category page), `search` (per query) or `category` (per category ID) |
| `targets` | `set` for search and category | The queries as shoppers type them, or category IDs from `list_categories` (`categoryId`). One rule can cover several (a product-type group) |
| `match_type` | search, optional | `EXACT_MATCH` (default) or `PHRASE_MATCH` |
| `rule_id` | `update`, `enable`, `disable`, `delete`; optional on `set` | The facet rule's ID |
| `facets` | `set`, `update` | Replaces whole lists: `{"boost": [...], "bury": [...], "hide": [...], "always_show": [...]}`. For boost and bury, the order is the display order (first = position 1) |
| `add` | `set`, `update` | Adds to the current lists. A boost or bury entry can be `{"facet": "product_size", "position": 1}`; a plain name goes last |
| `remove` | `set`, `update` | Takes names out of the lists: `{"always_show": [...]}`, or `{"all": [...]}` for every list |
| `enabled` | optional | `true` switches the rule on (its own batch and yes); `false` switches it off. A new rule is switched on afterwards unless this is `false` |
| `name`, `audience_id` | optional | Display name; an audience from `list_discovery_audiences` |
| `reason` | optional | The finding it fixes. Shown in the plan |

Example, from a `facet-optimizer` review:

```json
[
  {"action": "set", "scope": "global", "add": {"hide": ["cluster", "internal_sku"], "always_show": ["price"]},
   "remove": {"always_show": ["color_groups"]}, "reason": "Junk facets; price missing everywhere"},
  {"action": "set", "scope": "category", "targets": ["21200"], "add": {"boost": [{"facet": "product_size", "position": 1}]},
   "remove": {"all": ["rating", "gender"]}, "reason": "Dresses: size first; one-value gender and raw rating boosted"},
  {"action": "set", "scope": "search", "targets": ["pants", "jeans"],
   "facets": {"boost": ["gender", "product_size", "colors", "price"]}, "name": "Mixed-gender bottoms", "reason": "No gender filter"},
  {"action": "delete", "rule_id": 9104, "reason": "Disabled duplicate"}
]
```

Moving a facet between lists is done for you: adding it to `hide` takes it out of boost, bury and always show; adding it to `boost` takes it out of bury and hide.

**Not possible through the API** (the tools' own descriptions say so): value merges, renames, range buckets and value order. A change with `merge`, `rename`, `ranges`, `value_order`, `aliases_facets` or `value_configs_facets` is blocked; give the user the dashboard steps.

## What the plan does with each change

The plan uses the shared shape in the repo's authoring guide ("Plan files for write skills"). "Blocked" means `status: blocked`, with the reasons in `problems`.

| Situation | Plan |
|---|---|
| `set` for a target no rule covers | A `create` with `enabled: false`, then an `enable` change (`after_change` points at the create) in a batch of its own |
| `set` for a target exactly one rule covers, same audience, same targets | An `update` of that rule, not a duplicate. A disabled rule stays off unless `enabled: true` adds an `enable` |
| A rule covers part of the targets, or several rules cover them, for the same audience | Blocked: update one by `rule_id`, match its targets, or clean up first (`discovery-rule-cleanup`) |
| A rule on the target for a different audience | A warning; the plan goes ahead |
| A rule the plan needs isn't saved as `get_facet_rule` detail | Blocked: read it and pass `--rule` |
| A rule or target in a running test (`isLive`, `isAbTestLive`, or a bucket of an experiment whose status isn't in `finished_statuses`, or is missing) | Blocked. A global change is blocked by any experiment that isn't finished; a running test of a global rule blocks every change. Without the saved experiments, a plan with ready changes isn't built |
| `isEditable: false` | Blocked |
| A new facet to show that matches `never_show_words`, isn't in `list_facet_attributes`, or isn't facetable | Blocked. Hiding an unknown name is only a warning |
| The same facet both hidden and shown, or both boosted and buried | Blocked |
| A second change to the same rule or target | Blocked: plan one change per rule |
| A changed list ends up empty | A warning: sending `[]` hasn't been tested; `verify` shows whether it cleared |
| Nothing would change | `no_change` |
| `delete` | A batch of its own. The undo recreates the rule from the saved detail, switched off (with `facet_items` for merges, renames and ranges), then switches it on with its own yes if it was on |
| More than `max_changes_per_batch` ready creates, updates and switch-offs | Further batches. Each switch-on and each delete is always alone |

## The write tools (checked against their published schemas, 2026-11)

- `create_facet_rule` takes `queries` (each `query`, `queryType` `sitesearch`, `category` or `global`, `matchType`; a global rule is `{"query": "*", "queryType": "global"}`), `boosted_facets`, `buried_facets`, `excluded_facets` and `always_included_facets` as **lists** (order is position), `name`, `audience_id`, `enabled` (**default `true`**: always pass `false`), `started_at`/`ended_at` (ms), `facet_items` (raw items), `account_name`, `environment`, `site_group_id`.
- `update_facet_rule` takes `rule_id` and the same fields. It fetches the stored rule and merges: each facet list you send replaces that list; anything you leave out, or send as `null`, keeps its value. So a name, schedule or audience can't be cleared once set. `queries` replaces the whole list (this skill doesn't change queries).
- `delete_facet_rule` is permanent and fails with 400 "Customization is live" while the rule is in a running test.
- `get_facet_rule` returns `data.data`, with `customizationItems.boosted_facets` and `buried_facets` as `{facet: position}` maps, `excluded_facets` and `always_included_facets` as lists. Boosted facets are usually listed in `always_included_facets` too ("boost and always show"), so `verify` leaves them out when it compares always-show. A missing rule is a tool error (HTTP 404) whose text includes an internal URL: save it as `{"success": false, "error": "<text>"}` and never repeat the URL.
