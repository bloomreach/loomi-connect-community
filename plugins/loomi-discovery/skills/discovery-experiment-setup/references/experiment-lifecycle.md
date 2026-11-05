# Discovery experiment lifecycle, constraints and payloads

This reference is drawn from the Loomi Connect tool schemas. The write calls themselves have **not** been exercised by this skill's authors. Re-check each tool's schema before calling it, in case it has changed.

## Experiment state machine

```
                 create_discovery_experiment
                            │
                            ▼
                         DRAFT  ── no live impact; buckets and rules are linked but not serving
                            │
                            │ start_discovery_experiment   (LIVE immediately)
                            ▼
                        RUNNING ── traffic is split; every bucket's rule is set enabled + live
                            │       rules in the test can't be changed or deleted ("Customization is live")
                            │
                            │ end_discovery_experiment     (LIVE immediately; can't be undone)
                            ▼
                       COMPLETED ── winner_bucket_id given: that variant serves 100% of traffic
                            │       no winner: all variants disabled, traffic returns to default
                            │       a COMPLETED test can't be restarted
                            │ archive_discovery_experiment (no live impact; can be unarchived)
                            ▼
                        ARCHIVED
```

- Only a DRAFT can be started. Only a RUNNING test can be ended. Only a COMPLETED test can be archived.
- No Loomi Connect tool was found to edit or delete a DRAFT. Do that in the Discovery Dashboard.
- A DRAFT whose rules were deleted can't be started. `get_ranking_rule` returns 404 for the missing rule.

## Constraints to check before writing

| Constraint | How to check |
|---|---|
| Rules in a RUNNING test can't be updated or deleted | `isAbTestLive` in the ranking rule lists; `search_discovery_experiments` with `experiment_statuses="RUNNING"` |
| Only **one un-targeted global rule per queryType** (`global`, `sitesearch_global`, `category_global`). Others need an `audience_id`, or the API returns a 400 duplicate error | `list_ranking_rules_global`, then `get_ranking_rule` on each to read `audiences` (the list's `audienceName` can show null even when an audience is set) |
| Several enabled rules for the same query conflict unless they target different audiences | `list_site_search_ranking_rules` with `q=<query>`, then `get_ranking_rule` on each |
| `create_ranking_rule` defaults to `enabled: true`, which is **live for everyone at once** | Always pass `enabled: false` for a rule meant for a test |
| A rule variant (`create_ranking_rule_variant`) starts disabled and can't be scheduled | — |
| Bucket names: letters, numbers, spaces, underscores and hyphens only (anything else returns 400) | — |
| Bucket `traffic_percentage` values must add up to 100, and exactly one bucket has `control: true` | — |
| `success_metric` is one of `AOV`, `ATC_RATE`, `CR`, `RPV`. It's optional in the API but required in the Dashboard; always set it | — |
| Discovery writes sync asynchronously (seconds to minutes) | After a create, list the rules and check `syncStatus` is `SUCCESS` |

## Test patterns

**Pattern 1: Rule vs default** (does the rule help at all?). Use it when no enabled rule exists for the query.

1. `create_ranking_rule` with `enabled: false` → rule ID.
2. `create_discovery_experiment` with a control bucket **without** `customization_id` (default behaviour) and a test bucket with `customization_id` = rule ID.
3. `start_discovery_experiment`.

**Pattern 2: Rule A vs rule B** (which configuration is better?). Use it when an enabled rule already exists for the query, so the control is "today's rule".

1. `create_ranking_rule_variant` with `base_rule_id` = the existing rule → variant ID (starts disabled).
2. `create_discovery_experiment` with `control: true` on the existing rule's ID and `control: false` on the variant's ID. If this fails, stop: tell the user the variant's ID and state, and how to disable it.
3. Enable the variant with `update_ranking_rule(rule_id=<variant>, enabled=true)`, with its own "yes". The tool description says to enable it before creating the test, but this skill **never enables a rule before the experiment exists**. **Unverified:** whether enabling a variant makes it serve outside a test, so treat it as possibly live for all shoppers of the query.
4. `start_discovery_experiment`, straight afterwards.

**Pattern 3: Algorithm A vs algorithm B** (is a new or corrected ranking algorithm better?). A page's algorithm comes from a rule of type `ranking_algo` (`customizationItems.ranking_algo.id` = the `algoId`), or from the account default when no such rule covers the page. The rule-list tools leave `ranking_algo` rules out; the product grid's `customizations.explain` shows them, and `get_ranking_rule` reads one by ID. The `discovery-experiments` guide lists ranking algorithm changes among what can be tested, and a demo account held a draft experiment whose two buckets were a `ranking_algo` rule (`sitesearch_global`) and its variant.

- **3a, an algorithm rule covers the scope** (no audience, no schedule): `create_ranking_rule_variant(base_rule_id=<that rule>, ranking_algo_id=<new algoId>)` → variant (disabled); the draft experiment with `control: true` on the base rule and `control: false` on the variant; enable the variant with its own "yes"; start. As Pattern 2.
- **3b, the account default ranks the scope:** `create_ranking_rule(queries=<scope>, ranking_algo_id=<new algoId>, enabled=false)` → rule; the draft experiment with a control bucket without `customization_id` and a test bucket on the rule; start. As Pattern 1. **Untested:** whether the new rule's `ruleType` reads back as `ranking_algo` or `ranking`; check `customizationItems.ranking_algo.id` with `get_ranking_rule`.
- A rule with an audience or a schedule can't be tested, and `create_ranking_rule_variant` rejects it as a parent (the `discovery-merchandising` guide).
- Global scopes: `{"query": "*", "queryType": "sitesearch_global"}` (every search) or `"category_global"` (every category page), `matchType: "EXACT_MATCH"`. Only one un-targeted global rule per `queryType`; when one exists, it's the 3a base rule.
- The algorithm under test must be `Available` in `search_ranking_algorithms` and for the same page type (`KEYWORD` for search, `CATEGORY` for category pages).

## Payload templates

### create_ranking_rule (site search, for a test)

```json
{
  "account_name": "<account>",
  "name": "TEST mens belt - boost TH and Pacific, bury duplicates",
  "enabled": false,
  "queries": [{"query": "mens belt", "queryType": "sitesearch", "matchType": "EXACT_MATCH"}],
  "attribute_boost_bury": [
    {"name": "brand", "strength": 40, "type": "boost", "values": ["Tommy Hilfiger", "Pacific"]},
    {"name": "omni_score_atc_decayed", "strength": 0, "type": "boost"},
    {"name": "omni_score_conv_decayed", "strength": 0, "type": "boost"},
    {"name": "omni_score_revenue_decayed", "strength": 0, "type": "boost"},
    {"name": "omni_score_views_decayed", "strength": 0, "type": "boost"}
  ],
  "bury_product_ids": ["<duplicate pid>", "..."]
}
```

- `matchType`: `EXACT_MATCH` applies only to that exact search. `PHRASE_MATCH` also applies to longer searches that contain it (a rule for "mens belt" would also apply to "black mens belt").
- `attribute_boost_bury` entries use `{name, strength 0–100, type: boost|bury, values}`. Brand values must match the facet values exactly, including stray spaces. The four `omni_score_*` entries at strength 0 mirror what the Dashboard editor sends. Don't use a `{field, factor}` shape: it's accepted but shows an empty Attribute tab.
- When you read the rule back with `get_ranking_rule`, the boost appears in a different, nested shape: `{"rule": {"type": "clause", "operands": [{"type": "attribute", "name": "brand", "operands": [...]}]}, "strength": 40, "type": "boost"}`. That's expected.
- Other options: `boost_product_ids`, `freeze_products`, `sliced_attributes`, `ranking_algo_id`, `audience_id`, `started_at` and `ended_at` (Unix ms), and `customization_items` for `product_slots` or `explicit_filters`.

### create_discovery_experiment (Pattern 1)

```json
{
  "account_name": "<account>",
  "name": "Search terms - mens belt",
  "traffic_percentage": 100,
  "success_metric": "RPV",
  "note": "Boost Tommy Hilfiger and Pacific, bury duplicate listings",
  "buckets": [
    {"bucket_name": "Control", "traffic_percentage": 50, "control": true},
    {"bucket_name": "Brand boost", "traffic_percentage": 50, "control": false, "customization_id": 1234567}
  ]
}
```

`traffic_percentage` at the top level is the share of eligible traffic in the test. Bucket percentages split that share.

### Pattern 3a: create_ranking_rule_variant (new algorithm on today's algorithm rule)

```json
{
  "account_name": "<account>",
  "base_rule_id": 1234570,
  "name": "TEST search algorithm - corrected copy",
  "ranking_algo_id": "br-newcopy1"
}
```

The variant inherits the base rule's queries and scope. Then the experiment as in Pattern 2, with the base rule as control.

### Pattern 3b: create_ranking_rule (new algorithm where the default ranks today)

```json
{
  "account_name": "<account>",
  "name": "TEST search algorithm - corrected copy",
  "enabled": false,
  "queries": [{"query": "*", "queryType": "sitesearch_global", "matchType": "EXACT_MATCH"}],
  "ranking_algo_id": "br-newcopy1"
}
```

Then the experiment as in Pattern 1: control bucket without `customization_id`, test bucket on the new rule.

### start_discovery_experiment

```json
{"account_name": "<account>", "experiment_id": 12345}
```

### For reference only (not used by this skill)

- `update_ranking_rule(rule_id, ...)`: only the fields you pass change. Item types merge by type. `bury_product_ids` and `attribute_boost_bury` **replace** the existing list of that type.
- `end_discovery_experiment(experiment_id, winner_bucket_id?)`: see the state machine.
- `archive_discovery_experiment(experiment_id)`: COMPLETED only.
- `delete_ranking_rule(rule_id)`: permanent. It fails with 400 for a rule in a running test.
