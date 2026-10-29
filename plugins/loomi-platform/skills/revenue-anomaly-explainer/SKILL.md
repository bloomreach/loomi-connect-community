---
name: revenue-anomaly-explainer
description: Explains why revenue, conversion or order value changed on a Bloomreach Discovery site between one period and the one before, using Loomi Connect. It splits the change into traffic, conversion and order value; search, category and other; and device, finds the queries, categories, products and brands that moved most, checks likely causes such as recently changed merchandising rules, A/B tests started or stopped, tracking pixel problems and catalog feed failures, dates the change from the daily trend, and returns a ranked list of causes with evidence, confidence and next steps. Use when the user asks why revenue or sales dropped or spiked, why conversion or AOV fell, what changed last week, or wants a root-cause analysis of a KPI change.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery). Python 3 is optional, for the bundled breakdown script.
metadata:
  author: bloomreach
  version: "0.1.4"
  products: discovery
  access: read-only
---

# Revenue anomaly explainer

## What this does

Answers "why did revenue (or conversion, or order value) change?" for one Bloomreach Discovery account or site, comparing a period with the one before it. It does two things:

1. **Breaks the change down with maths that adds up.** Every split (traffic × conversion × order value; search, category and other; device; top queries, categories, products and brands) accounts for 100% of the change, so you can say "traffic explains $231k of the $297k drop".
2. **Checks the usual suspects.** Merchandising rules changed or scheduled in the window, A/B tests started or stopped, tracking pixel problems, catalog feed or index failures, and the day the change started.

The result is a **ranked list of causes**, each with its evidence, how much of the change it explains, a confidence level, and a next step. It often concludes that there is **no single cause**, or that the change is within normal week-to-week variation. Say so plainly when that's the case.

This skill only reads. It never changes anything.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Account and site | `list_discovery_accounts`, `list_discovery_sites` |
| Headline cards | `get_discovery_overall_performance`, `get_discovery_search_performance`, `get_discovery_category_performance` |
| Daily shape | `get_discovery_trend` |
| Contributors | `get_discovery_query_performance`, `get_discovery_category_performance_table`, `get_discovery_product_performance_table`, `get_discovery_brand_performance` |
| Rule changes | `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `search_redirects`, `list_site_search_media_rules`, `list_category_media_rules` |
| Tests | `search_discovery_experiments` |
| Data health | `get_pixel_health_status`, `search_discovery_catalogs`, `search_discovery_catalog_jobs` |

`search_discovery_catalog_jobs` is usually not listed directly: find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Do the same for any other tool you can't see. Check each tool's parameters before calling it. Use read tools only: `search_tools` also returns write tools; never call them.

**You need:** the account (and site, if it has sites), the metric (default revenue), and the period. If the user says "last week" or "this week", use the **last 7 days** (`days=7`); for "this month", `days=30`. For specific dates, pass `start_date` and `end_date` (`YYYY-MM-DD`); the tools compare with the equal-length period just before. To compare with a different period (for example the same week last year), also pass `compare_start_date` and `compare_end_date`.

### Rules for calling the tools

- **One call at a time.** Discovery allows 3 requests per second, shared with everything else the user runs. On HTTP 429 or 500, wait a few seconds and retry once with default parameters.
- **Large tables are saved to files.** A 100-row table is 60,000 to 90,000 characters. Keep the saved files: the script in step 4 reads them directly. Otherwise extract only the fields you need.
- **The cards don't say which dates they cover.** Data usually ends a day or two before today. Read the dates from `get_discovery_trend` (step 3) and quote them.
- **Never repeat people's email addresses.** Rule and experiment lists include `lastModifiedBy` and `user`. Refer to "the rule's last editor (shown in the app)", not the address.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/decompose_change.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the account and site

1. Call `list_discovery_accounts`. If the list is long, filter it for the account the user named, and ask if it's still ambiguous.
2. Call `list_discovery_sites`. If there's more than one site, ask which one, and pass its `site_group_id`, `domain_key` and `view_id` to every reporting call.
3. If the account has **no sites**, report at account level: leave out `site_group_id`, `domain_key` and `view_id`. Tell the user.

### 2. Get the headline cards

Make these calls with the same period parameters, and save each response:

1. `get_discovery_overall_performance`.
2. `get_discovery_search_performance`.
3. `get_discovery_category_performance`.
4. `get_discovery_overall_performance` three more times, with `device_type` set to `desktop`, `mobile` and `tablet`.

Each card has `current`, `previous` and `trends`. Use the raw counts (`revenue`, `visits`, `conversions`), not the rounded rates: conversion rate is `conversions ÷ visits` and average order value is `revenue ÷ conversions`, so **revenue = visits × conversion rate × AOV exactly**. "Conversions" are orders.

What to expect:

- **Devices add up.** In testing, the three device cards summed exactly to the overall card for revenue, visits and orders. If they don't, report the gap as "unexplained" (for example, an unknown device type).
- **Search + category doesn't.** A visit can include both a search and a category page, so their visits overlap, and their revenue is attributed separately. Work out **other** = overall − search − category, and call it approximate. If it comes out negative, say that attribution overlaps and skip the channel split.

If the user asked about conversion or AOV rather than revenue, still get revenue: the breakdown explains the metric they asked about inside the revenue identity.

### 3. Get the daily shape

Call `get_discovery_trend` with `tab="overall"`, `metric="revenue"` (or the metric the user asked about: `visits`, `conversion_rate`, `aov`, `rpv`) and the same period. It returns one row per day for the current and previous periods, with `cdate` (`YYYYMMDD`). The daily values add up to the card total.

- Quote the **dates** from `cdate`: "30 Sep to 6 Oct vs 23 to 29 Sep".
- **Days with no data are left out, and some show `$0.00`.** Pair days by date, not by position. Missing or zero days in either period are a data problem: report them first, and don't trust the comparison until you've chosen a period without gaps.
- For short periods, also call it once with `days=28` (or 4× the period) for context: is the "drop" really a return to normal after an unusually strong previous week? Compare the averages of the weeks before.
- If the change is in search or category only, call it again with `tab="search"` or `tab="category"`.

### 4. Get the contributors

Make these calls one at a time with the same period, and save each response:

| Table | Call | Why |
|---|---|---|
| Queries | `get_discovery_query_performance`, `sort="revenue"`, `page_size=100` | the queries behind the search change |
| Categories | `get_discovery_category_performance_table`, `sort="revenue"`, `page_size=100` (more if `total_rows` is higher) | the categories behind the category change |
| Products | `get_discovery_product_performance_table`, `sort="revenue"`, `page_size=100`, **and again** with `sort="prev_revenue"` | the second call catches products that fell out of the top 100 |
| Brands | `get_discovery_brand_performance`, `sort="revenue"`, `page_size=100` | brand mix |

Every row has current and `prev_*` values for revenue, visits and conversions. **Don't sort by `change_*`:** that puts tiny rows first.

**Brands over 30 days:** `get_discovery_brand_performance` with `days=30` has returned a wrong previous period, which inflates brand trends. For monthly periods, work out brand changes from the product table (group products by brand) instead. With `days=7` the figures matched.

Then run the breakdown script. Pass every file you saved; several files for one table are merged:

```bash
python3 <this skill's folder>/scripts/decompose_change.py --overall overall.json --search search.json --category category.json --device desktop=desktop.json --device mobile=mobile.json --device tablet=tablet.json --table queries=queries.json --table categories=categories.json --table products=products_rev.json,products_prev.json --table brands=brands.json --trend trend.json --offset-days <N>
```

Set `--offset-days` to the number of days in the period (7 for `days=7`, 30 for `days=30`, or the days from `start_date` to `end_date` inclusive), or, if you passed custom comparison dates, to the days between `start_date` and `compare_start_date`. It pairs each day with the right comparison day even when the first or last day is missing from the trend.

It prints JSON with:

- `overall.parts`: the revenue change split into `traffic`, `conversion` and `order_value`, adding up exactly to the change, plus each part's share of the change;
- `channels` and `devices`: the change by search / category / other and by device, each with its own traffic / conversion / order-value split;
- `tables.<name>`: the biggest fallers and risers with their share of the parent change (queries → search, categories → category, products and brands → overall), each row's main driver, and the `long_tail_remainder` that the fetched rows don't cover;
- `trend`: the daily gaps aligned by date, any `data_gaps` (missing or zero days), the `shape` of the change (a step from a date, concentrated on a few days, one-off days, or spread evenly), and `change_vs_noise`, the change compared with normal day-to-day wobble;
- `missing_values` (only when some value was missing or `NA`): which values were counted as 0.

If you can't run scripts, do the same maths by hand using [references/breakdown-maths.md](references/breakdown-maths.md), with the thresholds in [references/rules.json](references/rules.json). Don't fall back to percentage changes that don't add up.

### 5. Check the likely causes

Work through [references/cause-checklist.md](references/cause-checklist.md). In short, one call at a time:

1. **Rules changed or scheduled in the window.** Call `list_site_search_ranking_rules`, `list_category_ranking_rules` and `list_ranking_rules_global` with `sort_by="lastModifiedAt"`, `sort_order="DESC"` and `limit=50`, and `search_redirects` and the media rule lists the same way. Keep rules whose `lastModifiedAt`, `createdAt`, `startedAt` or `endedAt` (Unix milliseconds) falls between the start of the comparison period and the end of the current period. **A scheduled rule can start or expire without being edited**, so check `startedAt`, `endedAt` and `durationTag` too. Match each rule's `queries[].query` (a search term, or a category ID for category rules) to the contributor tables.
2. **Experiments.** Call `search_discovery_experiments` with `sort_by="STARTED_AT"` and `limit=20`. Keep tests whose `startedAt` or `endedAt` falls in the window, and any that are `RUNNING`. A test that ended with a winner switches 100% of that query's or category's traffic to the winning rule.
3. **Tracking.** Call `get_pixel_health_status` with `period_hours=168`, then `336`. The previous week's count for each pixel type is the 336-hour count minus the 168-hour count. Compare `conversion-pageview` (orders) and `search-pageview`/`category-pageview` week on week with the card changes, and note issue rates. **The pixel window ends now, while the dashboard ends a day or two earlier**, so treat small differences (under ~5%) as noise. A tracking problem shows up as a pixel count or issue rate that moves much more than the business metric. For a full check, offer the `data-feed-health` skill.
4. **Catalog.** Call `search_discovery_catalogs`, then `search_discovery_catalog_jobs` (via `call_tool`) with `catalog_name`, `account_name` and `limit=50`. Look for failed product feed or index jobs, warnings, or a fall in `stats.product_doc_count` during the window. Check each job's `status` yourself: the `status` filter is ignored. 50 jobs covered about five days in testing, so for longer windows note that older jobs weren't checked.
5. **Daily shape.** From the script's `trend`: **data gaps** come first (missing or zero days are a reporting or tracking outage); a **step** on one date points to a change made that day (match it to rules, tests, jobs); **concentrated** or **one-off days** point to an outage, a promotion or an email send on those dates, or to unusually strong days in the comparison period; **spread evenly** points to demand, seasonality or traffic sources rather than a site change.

If the Engagement side might matter (for example a big email or SMS send in one period but not the other), say so and offer the `engagement-campaign-digest` skill. Don't run Engagement queries in this skill.

### 6. Rank the causes

Build a list of candidate causes. For each, give:

- **what** it is, in plain words;
- **how much** of the change it explains, in money and as a share, taken from the breakdown (for example "'diamond' search: −$34.9k, 28% of the search drop, 12% of the total");
- **the evidence**: the numbers, dates and rules that support it;
- **confidence**, using these rules:

| Confidence | When |
|---|---|
| **High** | The timing matches (a step on the day of a rule change, test or job failure), the affected query, category or device accounts for most of the change, and nothing else explains it |
| **Medium** | Two of the three: timing, size, or a plausible mechanism |
| **Low** | Plausible, but small or untimed; or the change is within normal variation |

- **next step**: a specific check or a skill to run (see the table below).

Rank by money explained, then confidence. Causes found in different cuts (a query, a device, a day) can overlap: say so, and work out the unexplained remainder as the total change minus the causes you list. Put a **data problem first** if one exists, because it makes the other numbers unreliable. Always include a line for the share that **no specific cause explains**, for example "broad traffic decline across all devices: about 78% of the drop".

| Finding | Next step |
|---|---|
| One query falls (conversion or relevance) | `discovery-query-diagnosis` on that query |
| Many queries or demand themes shift | `discovery-trending-searches` |
| Zero-result or dead-end queries rise | `discovery-zero-results-triage` |
| A category or group of categories falls | `discovery-category-health` |
| A rule changed or is stale | `discovery-rule-audit`; for a ranking change, consider `discovery-experiment-setup` to A/B test it |
| A test started, stopped or shipped a winner | `discovery-experiment-readout` |
| Pixel or catalog problem | `data-feed-health` |
| Email or SMS volume changed | `engagement-campaign-digest` |

## Output

```
## Why revenue changed: <account/site>, <dates> vs <dates>

**Answer:** <one or two sentences: the size of the change, the main driver, and whether there's a specific cause or it's broad/normal variation>

### The change, broken down
| | This period | Previous | Change | Share of change |
|---|---|---|---|---|
| Revenue | ... | ... | −$297k (−3.7%) | 100% |
| ↳ Traffic (visits) | ... | ... | −2.9% | −$231k (78%) |
| ↳ Conversion | ... | ... | +0.1 pts | +$8k (−3%) |
| ↳ Order value (AOV) | ... | ... | −0.9% | −$74k (25%) |

**By channel:** search −$126k (43%), category −$94k (32%), other −$77k (26%, approximate)
**By device:** desktop −$187k (63%), mobile −$87k (29%), tablet −$22k (7%)
**When:** <shape: step from date / one-off days / spread evenly>; <change vs normal variation>

**Biggest contributors**
- Queries: <query: −$, share, main driver>; ...
- Categories: ...
- Products / brands: ...

### Likely causes (ranked)
1. **<cause>**: explains about <$ / %>. Evidence: <...>. Confidence: <High/Medium/Low>. Next: <check or skill>.
2. ...
N. **Not explained by a specific cause:** <$ / %>: <e.g. traffic down evenly on every device>.

**Checked and ruled out:** <rules, tests, pixel, catalog: one line each>
**Caveats:** <account-level reporting, overlapping attribution, pixel window offset, long-tail share not covered>
```

Keep the whole answer to about one screen. Round money to the nearest thousand, and make the shares add up to 100% (allow ±1 for rounding).

## Safety

This skill is **read-only**. It never creates, changes, enables, disables or deletes rules, experiments, catalogs or anything else, and it never re-runs jobs.

This skill never uses a write tool, even if asked. If the user asks to fix something (for example roll back a rule), give the exact change (what, where and the values) for them to make in the Bloomreach Discovery dashboard, or hand off to a skill that writes, such as `discovery-experiment-setup` to test a ranking change. Warn them that **Discovery changes go live immediately**, that deletes can't be undone, and that changes are blocked while an A/B test runs.

Don't repeat email addresses from rule or experiment lists, or user IDs, cookies or IP addresses from pixel samples.
