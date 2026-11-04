# Example: applying a facet review

All names, IDs and figures below are invented.

**Prompt:** "Apply the facet optimizer's top three fixes for acme_demo in staging: hide cluster and stop always-showing colour groups everywhere, show size first on the dresses category, and give skirts searches size and colour filters. Also delete the old denim facet rule."

**Change file:**

```json
[
  {"action": "set", "scope": "global", "add": {"hide": ["cluster"], "always_show": ["price"]},
   "remove": {"always_show": ["color_groups"]}, "reason": "Junk facets; no price filter"},
  {"action": "set", "scope": "category", "targets": ["21200"], "add": {"boost": [{"facet": "product_size", "position": 1}]},
   "remove": {"all": ["rating", "gender"]}, "reason": "Dresses: size first"},
  {"action": "set", "scope": "search", "targets": ["skirts"], "add": {"boost": ["product_size", "colors"]},
   "name": "Skirts facets", "reason": "No rule for skirts"},
  {"action": "delete", "rule_id": 9106, "reason": "Disabled, replaced by 9102"}
]
```

**Plan (staging), after reading the three rule lists, rules 9101, 9102 and 9106, the facet attributes, categories and running tests.** Batches: `[1, 2, 3]`, then `[4]`, then `[5]`.

| # | Change | Rule and pages | Before | After | Live impact | Warnings |
|---|---|---|---|---|---|---|
| 1 | update | 9101, all pages (global) | hide: countryOfOrigin; always show: category, color_groups, brand, colors | hide: countryOfOrigin, cluster; always show: category, brand, colors, price | live | Rule 9101 already covers all pages: updated, not duplicated |
| 2 | update | 9102, category 21200 | boost: colors, rating, gender | boost: product_size, colors | live | Rule 9102 already covers category 21200 |
| 3 | create (switched off) | new, search 'skirts' | — | boost: product_size, colors | none | — |

Each on its own:

| # | Change | Rule and pages | Before | Undo |
|---|---|---|---|---|
| 4 | enable (after change 3) | new, search 'skirts' | off | `update_facet_rule` enabled=false |
| 5 | delete | 9106, category 50100 (off, audience 77) | boost: brand; a material merge | recreate switched off with `create_facet_rule` (new ID, merge in `facet_items`) |

> Make changes 1, 2 and 3 in staging? Rule 9101 changes every search and category page. (yes / no)

**User:** "yes"

Changes 1 to 3 are written one at a time; each is read back with `get_facet_rule` until `syncStatus` is `SUCCESS`. The create returned rule 9210, which replaces `<id returned by change 3>` in change 4.

> Switch on the new facet rule 9210 for search 'skirts'? Shoppers searching 'skirts' will see size, then colour, first. (yes / no)

**User:** "yes"

> Delete facet rule 9106 (category 50100)? It can't be undone, only recreated with a new ID. It's already off: keep it off instead? (delete / keep off / skip)

**User:** "delete"

The read-back of 9106 is a not-found error, saved as `{"success": false, "error": "..."}`.

**Verify:** `facet_rule_plan.py verify` with the read-backs of changes 1 to 5: changes 1 to 4 `in_place` (sync `SUCCESS`), change 5 `gone`. The product grid for "skirts" now lists `product_size` first.

**Result:**

| # | Change | Rule and pages | Result | Sync | Undo |
|---|---|---|---|---|---|
| 1 | hide cluster, always show price, drop color_groups | 9101, all pages | in place | SUCCESS | `update_facet_rule` excluded_facets=[countryOfOrigin], always_included_facets=[category, color_groups, brand, colors] |
| 2 | size first; rating and gender off | 9102, category 21200 | in place | SUCCESS | `update_facet_rule` boosted_facets=[colors, rating, gender], always_included_facets=[gender, rating, colors] |
| 3 | created, off | 9210, search 'skirts' | in place | SUCCESS | `delete_facet_rule` 9210 |
| 4 | switched on | 9210, search 'skirts' | in place | SUCCESS | `update_facet_rule` enabled=false |
| 5 | deleted | 9106, category 50100 | gone | — | recreate from `plan-staging.json` |

**Dashboard only:** none. **Undo plan:** `plan-staging.json`. **Next:** check the staging site, then build the production plan.
