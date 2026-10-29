# RAG thresholds and pixel issue keys

The numbers live in [rules.json](rules.json) (each key explained under its `notes`) and the pixel issue fixes in [pixel-fixes.json](pixel-fixes.json). Read both: this page only says how the rules fit together, by key name, so it can't drift from them. `scripts/discovery_jobs_summary.py` and apps that rate the same data read the same files.

## Thresholds

Use these as defaults. If the user has their own service levels (for example "the feed must run every 6 hours"), use theirs instead.

### Discovery pixel (per pixel type)

Read issue rates from `get_pixel_health_status` with `period_hours` = `pixel_period_hours`, and the baseline from a 7-day (168-hour) call: its count ÷ 7 is the daily average.

| Status | Rule |
|---|---|
| RED | A core type has an issue rate of `pixel_red_issue_pct` or more; **or** it has no events in `pixel_period_hours` while other page types have traffic; **or** its count is below `pixel_red_volume_ratio` of its 7-day daily average |
| AMBER | Issue rate from `pixel_amber_issue_pct` up to `pixel_red_issue_pct`; **or** the count is between `pixel_red_volume_ratio` and `pixel_amber_volume_ratio` of the 7-day daily average |
| GREEN | Issue rate below `pixel_amber_issue_pct` and the count is steady |
| NOT IN USE | No events in 7 days for a type the site may not implement (content, thematic, quickview, impressions types) |

Core types are `core_pixel_types`. Add `suggest-event` and the `widget-*` events if the site uses autosuggest or recommendation widgets. A type outside them is at most AMBER on issue rate.

Small numbers of `cdp_segments_invalid` issues (well under `pixel_amber_issue_pct`) are common and don't need action on their own.

### Catalogs and jobs

Read `jobs_limit` jobs per catalog. A job's kind is `feed:<properties.feed_data_type>`, `index:<properties.index_mode>` or its `type` (`suggest`, `other`). A run succeeded when its status is `success_status` and failed when its status is one of `failed_statuses`. `core_kinds` keep the product catalog current.

| Status | Rule |
|---|---|
| RED | The latest job of a core kind failed; **or** no success of any core kind for more than `stale_hours` (or twice the usual cadence), or none at all; **or** a kind's product count fell `count_drop_red_pct`% or more between its two latest successful jobs; **or** the latest run of a Data Hub or v2 Engagement catalog job type failed |
| AMBER | The latest job of another kind failed; failures followed by a later success; a successful job with a warning in its status message; a product-count drop from `count_drop_amber_pct`% up to `count_drop_red_pct`%; the freshest core success older than `aging_share` × `stale_hours`; standard events or the main catalog not mapped in Engagement |
| GREEN | Recent successes on the usual cadence, no warnings, steady counts |
| NOT ENABLED | The workspace has no Data Hub (`data_engine_url` is null) |
| NOT VISIBLE | Loomi Connect can't show freshness, for example v1 Engagement catalogs |

Work out the usual cadence from the gaps between successful runs of the same job kind in the list.

## Pixel issue keys

[pixel-fixes.json](pixel-fixes.json) lists the `status_key` values seen in testing, keyed by the key, each with its likely `meaning` and the usual `fix` (written to pass on to a merchandiser). For a key not listed, use its `fallback_fix`. Confirm the cause with `get_pixel_event_details` on one sample event before reporting it.

## Tool quirks seen in testing

- `get_pixel_health_status` can return an empty `top_issues` list for a type with a 100% issue rate over longer windows (for example 168 hours). Use the 24-hour call to read the issue keys.
- `search_discovery_catalog_jobs` ignored the `status` filter. Filter jobs by `status` yourself.
- `search_discovery_catalogs` reports `last_index_refresh_at` for full refresh indexes only. Daily update indexes in the job list can be newer.
- `search_datahub_jobs` with a `project_id` returned no jobs and a hint to try `workspace_id`. A workspace without `data_engine_url` returns an error saying Data Hub may not be enabled.
- `list_catalog_jobs` works only for v2 Engagement catalogs.
