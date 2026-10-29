---
name: data-feed-health
description: Checks the health of the data Bloomreach depends on, using Loomi Connect - the Discovery tracking pixel, Discovery catalog feed and index jobs, Data Hub jobs and catalogs, Engagement catalog jobs and event mapping - and returns a red, amber and green summary with next steps. Use when the user asks whether feeds or catalogs are up to date, if the pixel or tracking is broken, why data looks stale or missing, about failed imports or catalog jobs, or wants a data health check before trusting reports.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery; optionally Data Hub and Engagement).
metadata:
  author: bloomreach
  version: "0.1.4"
  products: discovery,datahub,engagement
  access: read-only
---

# Data and feed health check

## What this does

Every other report depends on two things: **tracking** (the Discovery pixel that records page views, searches, add-to-carts and orders) and **catalog data** (the product feeds and the jobs that index them). This skill checks both and returns one red, amber and green (RAG) summary, with the evidence and the next step for each problem.

It covers:

1. **Discovery pixel**: which pixel types have errors, which expected events are missing, and why.
2. **Discovery catalog**: when the product feed and index last succeeded, failures, warnings and product-count drops.
3. **Data Hub** (if enabled): failed or stale pipeline jobs, and which catalogs it manages.
4. **Engagement** (optional): catalog job history and whether standard events and the product catalog are mapped.

This skill only reads. It never re-runs jobs, uploads data or changes settings. For Engagement event tracking and data quality (event volumes, junk events, property fill rates), use `engagement-tracking-health`.

## Before you start

This skill uses these Loomi Connect tools:

| Area | Tools |
|---|---|
| Discovery account | `list_discovery_accounts`, `list_discovery_sites` |
| Discovery pixel | `get_pixel_health_status`, `get_pixel_event_stream`, `get_pixel_event_details` |
| Discovery catalog | `search_discovery_catalogs`, `search_discovery_catalog_jobs` |
| Organisation and projects | `list_cloud_organizations`, `list_workspaces`, `list_projects` |
| Data Hub | `search_datahub_jobs`, `search_datahub_catalogs` |
| Engagement | `search_catalogs`, `list_catalog_jobs`, `get_mapping` |

`search_discovery_catalog_jobs` is usually not listed directly: find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Do the same for any other tool you can't see. Check each tool's parameters before calling it. Use read tools only: `search_tools` also returns write tools; never call them.

Ask the user which parts to check. By default, check the Discovery pixel and catalog, plus Data Hub and Engagement if the user has access to a cloud organisation.

### Rules

- **Make calls one at a time.** Discovery and Engagement each allow about 3 requests per second. If a call returns HTTP 429, wait a few seconds and retry.
- **Never look at individual customer records.** This skill needs status, counts and configuration only. Don't call customer or event-listing tools. `get_pixel_event_details` returns one event's raw parameters, including a masked user ID and IP address: use it only to see which parameter is wrong, and **never copy user IDs, cookies, IP addresses or segment values into the report**.
- **Prefer sandbox or test projects** when the user has a choice. In production, read only job and catalog status.
- **Don't trigger anything.** If a job has failed, report it and say who can re-run it. Never call tools that start, re-run, import or update.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/discovery_jobs_summary.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the scope

1. **Discovery:** call `list_discovery_accounts` and, if the user named an account, filter for it. Call `list_discovery_sites`. If the account has no sites, check at account level (leave out `site_group_id`) and say so.
2. **Data Hub and Engagement:** call `list_cloud_organizations`, then `list_workspaces`. If there's more than one organisation, workspace or project, **list them and ask the user which to use. Never guess.** A workspace whose `data_engine_url` is null **doesn't have Data Hub enabled**: report Data Hub as "not enabled", not as a failure.

### 2. Discovery pixel

1. Call `get_pixel_health_status` with `period_hours=24`. It returns page-view pixels and event pixels, each with `event_count`, `issue_count`, `issue_rate_pct` and `top_issues`.
2. Call it again with `period_hours=168` (7 days) to get a baseline. Compare each type's 24-hour count with its 7-day daily average (7-day count ÷ 7). Longer windows can leave `top_issues` empty even at a 100% issue rate, so read the issue keys from the 24-hour call.
3. Rate each pixel type with the thresholds in [references/rules.json](references/rules.json), as [references/rag-thresholds.md](references/rag-thresholds.md) explains. In short:
   - **Red:** a core type has an issue rate of `pixel_red_issue_pct` or more, or no events at all although the site has traffic, or its count is below `pixel_red_volume_ratio` of its daily average.
   - **Amber:** an issue rate of `pixel_amber_issue_pct` or more, or a count below `pixel_amber_volume_ratio` of its daily average.
   - **Green:** below `pixel_amber_issue_pct` and steady.
   Core types are `product-pageview`, `category-pageview`, `search-pageview`, `conversion-pageview`, `atc-event` and `search-event`. Types with zero events, such as `content-pageview`, `thematic-pageview`, `quickview-event` or the `*-impressions-pageview` types, are often simply not implemented: list them as "not in use", not as red, unless the user expects them.
4. For each red or amber type, call `get_pixel_event_stream` with `display_types=[<type>]`, `status_keys=[<top issue>]`, `max_events=5` and the same period. Note the device spread.
5. Call `get_pixel_event_details` for **one** sample event (its `pixel_id` and `timestamp`) to see which parameter causes the issue, for example a missing `catalogs` parameter or an invalid `url`. Explain the issue in plain words, with its fix, from [references/pixel-fixes.json](references/pixel-fixes.json).

### 3. Discovery catalog

1. Call `search_discovery_catalogs` (no `catalog_name`). For each catalog and environment, note `product_doc_count`, `last_index_refresh_at` and `data_hub_properties`. If `data_hub_properties` is not empty, the catalog is **managed by Data Hub**: check it in step 4 instead, because the Discovery job tool returns an error for Data Hub catalogs.
2. Call `search_discovery_catalog_jobs` (via `call_tool`) with `catalog_name`, `account_name` and `limit` = `jobs_limit` from [references/rules.json](references/rules.json). Jobs have a `type` (`feed`, `index`, `suggest`, `other`), a `status`, timestamps, `properties.feed_data_type` (`products` is the product feed; `ae`, `qd`, `ltr` and `product_vectors` are internal signals) and `stats.product_doc_count` on index jobs.
   - **The `status` filter may be ignored by the server.** In testing, `status="failure"` returned successful jobs. Always check each job's `status` yourself.
   - **Use the jobs, not `last_index_refresh_at`, for freshness.** That field only tracks full "refresh" indexes; daily "update" indexes can be newer.
3. Summarise with [scripts/discovery_jobs_summary.py](scripts/discovery_jobs_summary.py) if you can run scripts:

   ```
   python3 <this skill's folder>/scripts/discovery_jobs_summary.py jobs.json
   ```

   It reports, per job kind, the latest success, hours since it, failures, warnings and product-count changes, and suggests a RAG status using [references/rules.json](references/rules.json). Otherwise work it out by hand with those rules ([references/rag-thresholds.md](references/rag-thresholds.md) says how they fit together):
   - **Red:** the latest product feed or index job failed; no successful product feed or index for more than `stale_hours` (or twice the usual cadence); a product count fell `count_drop_red_pct`% or more.
   - **Amber:** a successful job with a warning in `status_message` (for example "Feed data contains null values"); earlier failures that later succeeded; a count drop of `count_drop_amber_pct`% or more; last success older than `aging_share` × `stale_hours`.
   - **Green:** recent successes on the usual cadence, no warnings, steady counts.
4. A staging catalog with no documents is normal if the account only uses production. Mention it only if the user works in staging.

### 4. Data Hub (if enabled)

Only for workspaces with a `data_engine_url`.

1. Call `search_datahub_jobs` with `workspace_id` and `limit=50`. Note each job's type, state and timing. Rate failed jobs red if they are the most recent run of that type, and amber if a later run succeeded. Rate as amber any job type whose last success is much older than its usual cadence.
2. Call `search_datahub_catalogs` with the `project_id`. Catalogs whose `item_collection_*` fields are set are fed by Data Hub. To see one collection's jobs, call `search_datahub_jobs` with `resource_type="item-collection"` and `resource_id=<collection name>` (the name, not the ID).
3. If `search_datahub_jobs` with `project_id` returns nothing, try the workspace scope, and the other way round.

### 5. Engagement (optional)

1. Call `list_projects` for the organisation and confirm the project with the user.
2. Call `search_catalogs` with the `project_id`. Each catalog has a `catalog_version`.
   - **v2 catalogs:** call `list_catalog_jobs` with `project_id`, `catalog_id` and `count=20`. Rate a recent `fail` state red, and older failures followed by success amber.
   - **v1 catalogs** have no job history in Loomi Connect (the tool returns "Catalog jobs are not available for v1 catalogs"). Report their freshness as "not visible; check in the Engagement app".
3. Call `get_mapping`. Note which **standard events** (`purchase`, `view_item`, `add_to_cart`, `search`, `view_category`) have no `event` mapped, and whether `catalogs.main` is set. Unmapped standard events or no main catalog is amber: features that rely on the mapping (such as recommendations, attribution and some reports) may not work. This reads configuration only, never customer data.

### 6. Summarise

Give each area one overall status: the worst of its checks. Write one line of evidence and one next step for every red or amber item. Order the next steps red first, then by how many reports they affect.

## Output

```
## Data and feed health: <scope>, checked <date, time UTC>

**Overall:** <RED / AMBER / GREEN>: <one sentence>

| Area | Check | Status | Evidence | Next step |
|---|---|---|---|---|
| Discovery pixel | search-pageview | RED | 100% of 26.5k events flagged `catalogs_required` | Add the catalogs parameter to the search page pixel |
| Discovery pixel | other core types | GREEN | < 0.1% issues | — |
| Discovery catalog | product feed + index | AMBER | last index 8h ago; feed warns of null values | Fix null fields in the feed |
| Data Hub | jobs | NOT ENABLED | workspace has no Data Hub | — |
| Engagement | catalogs | NOT VISIBLE | 3 v1 catalogs, no job history | Check imports in the app |
| Engagement | mapping | AMBER | no standard events mapped | Map purchase, view_item, add_to_cart |

**Not in use:** <pixel types with no events that seem not implemented>
**What this means for other reports:** <for example, "search reports undercount until the search pixel is fixed">
```

Use the status words RED, AMBER, GREEN, NOT ENABLED and NOT VISIBLE. Don't rely on colour alone.

## Safety

This skill is **read-only**. It never re-runs jobs, uploads or imports data, or changes pixel, catalog, mapping or Data Hub settings.

It never reads individual customer profiles or event histories, and it never puts user IDs, cookies, IP addresses or segment values from pixel samples into its output.

If the user asks to fix something, explain what needs to change and who usually owns it (the site's front-end team for pixels; whoever sends the feed for catalog data). Give the exact change (what, where and the values) for them to make in Bloomreach. This skill never uses a write tool, even if asked.
