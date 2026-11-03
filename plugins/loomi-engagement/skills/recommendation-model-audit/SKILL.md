---
name: recommendation-model-audit
description: Audits recommendation engines (models) in a Bloomreach Engagement project with Loomi Connect. It lists every engine with its type, catalog, event and filters, checks whether each catalog is fresh and healthy, finds where each engine is used in scenarios, email campaigns and web layers, and flags unused engines, engines on stale or failing catalogs, near-duplicates, engines with no or very restrictive filters or fallbacks, and important placements that use no recommendations, then returns a prioritised cleanup and improvement list. Use when the user asks for a recommendation engine audit, recommendations cleanup, which recommendation models are used or unused, duplicate engines, or why recommendations look empty, stale or wrong.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement). Python 3 is optional, for the bundled audit script.
metadata:
  author: bloomreach
  version: "0.1.4"
  products: engagement
  access: read-only
---

# Recommendation model audit

## What this does

Takes stock of every recommendation engine in one Engagement project and returns a **cleanup list** and an **improvement list**. It checks:

| Check | Why it matters |
|---|---|
| **Unused** engines (no placement references them) | Clutter, and they keep retraining for nothing |
| Engines on a **stale, failing or empty catalog** | They recommend sold-out, old or wrong products, or nothing |
| **Near-duplicate** engines (same type, catalog, event and filters) | Nobody knows which one is the "real" one; fixes land on one and not the other |
| **No filters, or very restrictive ones**, and no fallback | Unfiltered engines show out-of-stock or already-bought items; over-filtered ones return empty slots |
| **Important placements with no recommendations** | Missed revenue in abandoned-cart, browse-abandonment, post-purchase, home and product-page experiences |
| **Name doesn't match the type** | "Most popular" built as "recently viewed" shows the wrong thing |

It never changes anything. Catalog problems are handed to `data-feed-health`.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Project | `list_cloud_organizations`, `list_projects` |
| Engines | `search_recommendations` (list, then each by `recommendation_id`) |
| Catalogs | `search_catalogs`, `get_catalog_usages`, `list_catalog_jobs` (v2 catalogs only), optionally `search_catalog_items` |
| Placements | `search_scenarios`, `search_scenario_nodes` (via `search_tools` and `call_tool`), `search_email_campaigns`, `search_banners` |
| Smoke test (optional) | `get_customer_recommendations`, only with a test customer ID the user gives you |

If a tool isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. `search_scenario_nodes` is usually reached this way. Only ever use read tools: `search_tools` also returns write tools such as `update_scenario_node`; never call them.

### Rules for calling the tools

- **One call at a time.** Engagement allows about 3 requests per second per user, shared with everything else you run. On HTTP 429, wait at least 5 seconds and retry; if it happens again, wait 20 seconds.
- **`search_recommendations` can return HTTP 403** ("access denied") depending on the account's permissions. Stop and tell the user the audit can't run without access to recommendations; don't report "no engines".
- **There's no "where is this engine used" tool.** `get_catalog_usages` lists the engines built on a catalog, not where the engines are placed. Placements are found by searching definitions for the engine's ID (step 4).
- **Placement definitions are large and contain content.** Email designs, scenario node designs and web layer variants hold full HTML, Jinja and JavaScript. Never paste it into the answer. Only look for engine IDs in it. If the client saves responses to files, use [scripts/audit_engines.py](scripts/audit_engines.py), which prints only the matches.
- **Never repeat personal data.** Engine, catalog and scenario records include `created_by_display_name` and `edited_by_display_name`. Never repeat them. Describe things by name, type and status only.
- **Aggregate only.** Never call `list_customers`, `get_customer_properties` or `list_customer_events`. Don't pick a customer for the smoke test yourself.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/audit_engines.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the project

If the user named a project, use it. Otherwise call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and **ask which one to use**. Never guess. Say whether it's a sandbox or production project: sandboxes often have no engines at all.

### 2. List the engines and fetch their definitions

1. `search_recommendations` with only `project_id`. Each record has `_id`, `name`, `status` (for example `running`), `archived`, `tags`, `initiative_id`, `created` and `edited` (Unix timestamps). An empty list means the project has no engines: say so, and go straight to step 5 (placements with no recommendations).
2. For each engine that isn't archived, call `search_recommendations` with `recommendation_id`, one at a time. From `definition`, keep:

| Field | Meaning |
|---|---|
| `type` | The algorithm (for example `recently_viewed`) |
| `mapping.catalog` | The catalog ID it recommends from |
| `mapping.filter` | Catalog filters (which items may be recommended) |
| `event.event_type`, `event.attribute.property` | The behaviour it learns from (for example `view_item` and `product_id`) |
| `event_filter` | Filters on those events |
| `date_filter` | Event look-back window: `enabled`, and `duration` (`count`, `units`) or `from_date`/`to_date` |
| `blacklist_enabled`, `blacklist`, `blacklist_rules` | Exclusions (for example items already bought) |
| `dynamic_catalog_filter_enabled`, `dynamic_catalog_filters` | Per-customer catalog filters |
| `customer_preferences_enabled`, `customer_preferences` | Preference boosting |
| `pinning_pid_enabled`, `pinning_attribute_filter_enabled` and their rules | Pinned items |
| `status`, `model_id` | Engine state and its model |

### 3. Check the catalogs

For each distinct `mapping.catalog`:

1. `search_catalogs` (list, once) gives each catalog's `name`, `type`, `catalog_version` (`v1` or `v2`) and `is_product_catalog`. A catalog ID that isn't in the list means the engine points at a **deleted catalog** (Action).
2. `get_catalog_usages` with `catalog_id`: its `used_by.recommendations` lists the engines built on that catalog (a cross-check for step 2), and the other `used_by` keys show what else depends on the catalog.
3. **Freshness:**
   - **v2 catalogs:** `list_catalog_jobs` with `count=20`. Look at the latest jobs' `type`, `state` (`pending`, `running`, `success`, `fail`, `canceled`) and `created`. Flag the catalog **failing** if the latest import or update job failed, and **stale** if the last successful one is older than 7 days (2 days for catalogs that hold price or stock). No jobs at all: "no update history"; say so.
   - **v1 catalogs:** `list_catalog_jobs` returns "Catalog jobs are not available for v1 catalogs", and v1 catalog records have no `edited` date. Report freshness as "unknown (v1 catalog)". Optionally call `search_catalog_items` with `count=5` to confirm the catalog isn't empty, and only look at item count and field names, not values.
4. Any catalog problem goes to the hand-off (see Output). Don't diagnose feeds here.

### 4. Find where each engine is used

Engines are referenced by their `_id` inside content: Jinja in emails and web layers (for example `recommendations('<engine id>', ...)`), JavaScript in web layers, or a recommendation block in an email design. Search for each engine ID, one call at a time, in this order, and stop early for an engine once it's found in an active placement:

1. **Active scenarios:** `search_scenarios` with `status="active"`. For each, fetch it by `scenario_id` with `include_node_designs=True` and look for engine IDs in the action nodes (`send-email-action`, `serve-banner-action`, `push-notification-*`, `send-app-inbox-action`, `per-customer-webhook-action`). Without `include_node_designs=True` the designs are stripped and you'll find nothing. Designs can be 70 KB+ per node; if one scenario is too large, use `search_scenario_nodes` (via `search_tools` and `call_tool`) to list the nodes and fetch only the action nodes with `include_design=True`.
2. **Email campaigns:** `search_email_campaigns` with `status="active"`, then each by `campaign_id` with **`include_design=True`**. The default strips `jinja_html` and `beefree_template`, which is where engine IDs live.
3. **Web layers:** `search_banners` with `serving_status="serving"`, then each by `banner_id`. Look in the variants' HTML, script and parameters.

Record each match as *engine → placement name, type, status*. Don't record the content around the match.

If the user only wants a quick audit, do 1–3 for active placements only and say inactive ones weren't searched. An engine found nowhere is **"not found in active placements"**, not "unused": it may be called from the website through the API, or from an inactive draft.

### 5. Look for important placements with no recommendations

From the placements you listed in step 4, pick out the ones where recommendations usually earn the most, by name and node type:

- abandoned cart, abandoned browse or product view, post-purchase or cross-sell, welcome, win-back, back-in-stock or price-drop emails;
- web layers on the home page, product pages, cart or a 404 or zero-results page.

If one is active and references **no** engine, flag it as an **Opportunity**. Say which engine type would suit it (see [references/audit-checks.md](references/audit-checks.md)).

### 6. Apply the checks

Read [references/audit-checks.md](references/audit-checks.md) for the full rules and severities. In short:

- **Action:** engine on a deleted, failing or empty catalog; engine used in an active placement whose catalog is stale; an engine that isn't `running` but is used in an active placement.
- **Review:** near-duplicates (same `type`, catalog, event, look-back and filters); no catalog filter and no exclusions on a product engine; very restrictive filters (several catalog filters, a look-back under 7 days, or pinning that fills the slot); the name doesn't match the type; catalog freshness unknown.
- **Opportunity:** important placements with no recommendations.
- **Cleanup:** engines not found in any placement and not edited for 90+ days; names with test, copy, old, dev, POC, QA, sandbox.

If you can run Python, save the engine detail responses, the catalog list and any placement responses to files and run:

```bash
python3 <this skill's folder>/scripts/audit_engines.py --engines engine_*.json --catalogs catalogs.json --jobs jobs_<catalogId>.json --placements scenario_node_*.json email_*.json banner_*.json
```

It prints each engine's summary, duplicate groups, catalog problems and the placements that reference each engine, without printing any content.

### 7. Optional smoke test

Only if the user gives you a test customer's external ID and ID type: `get_customer_recommendations` for each used engine with `size=5`. An empty list confirms an empty-slot problem. Report only the number of items returned and whether they exist in the catalog, never the customer ID. This call doesn't track impressions.

### 8. Prioritise

Order: **Action** → **Opportunity** (by placement reach: active scenarios with high send volume and site-wide web layers first) → **Review** → **Cleanup** (grouped if there are more than 10). For each, say what to do and who usually does it: the marketer who owns the placement, the web team for web-layer code, or the data team for catalog feeds.

## Output

```
## Recommendation model audit: <project>, <date>

**Verdict:** <one sentence: the most important problem, and how many engines are used vs not>

**Inventory:** <n> engines (<running> running, <archived> archived) on <k> catalogs; placements searched: <active scenarios n, email campaigns n, web layers n>

### Engines
| Engine | Type | Catalog (freshness) | Learns from | Filters / exclusions | Used in |
|---|---|---|---|---|---|

### Fix now
| Engine or placement | Problem | Evidence | Do this |
|---|---|---|---|

### Add recommendations here
| Placement | Type | Why | Suggested engine type |
|---|---|---|---|

### Review
- <near-duplicate groups, missing or restrictive filters, name/type mismatches>

### Clean up
- <unused or test engines: archive after confirming they aren't called through the API>

**Catalog hand-off:** <catalogs that are stale, failing, empty or of unknown freshness>: run `data-feed-health` on them.
**Not checked:** <403s, inactive placements not searched, API or website usage, v1 catalog freshness>
```

Never include placement HTML, Jinja, scripts, editor names, customer IDs or catalog item values.

## Safety

This skill is **read-only**. It never edits, retrains, archives or deletes an engine, catalog or placement. If the user wants to act on the list, tell them to do it in the Engagement UI, and to check first that the website or another system doesn't call the engine through the API.
