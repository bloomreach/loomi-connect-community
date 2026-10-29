---
name: weekly-ecommerce-briefing
description: Builds a one-screen Monday-morning ecommerce briefing from Bloomreach Discovery and Engagement using Loomi Connect - headline KPIs this week against last (revenue, revenue per visit, conversion and average order value, overall, search, category and by device), the top search terms and top categories, the searches and categories with problems (dead ends, low conversion, high bounce, falling revenue) ranked by revenue at stake, the top moving search queries, categories, products and brands, email and SMS campaign highlights, tracking pixel and catalog feed health alerts, and three things to do this week, each linked to the skill that does it. Use when the user asks for a weekly briefing, weekly report, Monday update, how last week went, top searches or categories, which searches or categories have problems, a KPI summary for the team, or what to focus on this week. Works with Discovery only, Engagement only, or both.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery and/or Bloomreach Engagement). Python 3 is optional, for the bundled numbers script.
metadata:
  author: bloomreach
  version: "0.2.4"
  products: discovery,engagement
  access: read-only
---

# Weekly ecommerce briefing

## What this does

Produces a short briefing a merchandiser or ecommerce manager can read in two minutes on a Monday morning:

1. **Headline KPIs**, this week against last: revenue, revenue per visit (RPV), conversion rate and average order value (AOV), overall and split into search, category and device.
2. **Top searches and categories**, and **the searches and categories with issues**: dead ends, low conversion, high bounce or falling revenue, ranked by revenue at stake.
3. **Top movers:** the search queries, categories, products and brands that moved most.
4. **Marketing:** email and SMS campaign highlights from Engagement, if a project is given.
5. **Health alerts:** tracking pixel and catalog feed problems that make the numbers unreliable.
6. **Three things to do this week**, each linked to the skill that does it.

It's a summary, not a deep dive. Each section borrows the method of a more detailed skill and points to it by name for the full analysis.

This skill only reads. It never changes anything.

## Before you start

This skill uses these Loomi Connect tools:

| Section | Tools |
|---|---|
| Account and site | `list_discovery_accounts`, `list_discovery_sites` |
| KPIs | `get_discovery_overall_performance`, `get_discovery_search_performance`, `get_discovery_category_performance`, `get_discovery_trend` |
| Top, issues and movers | `get_discovery_query_performance` (including the `no_search_results` and `no_revenue` presets), `get_discovery_category_performance_table`, `get_discovery_product_performance_table`, `get_discovery_brand_performance` |
| Health | `get_pixel_health_status`, `search_discovery_catalogs`, `search_discovery_catalog_jobs` |
| Marketing | `list_cloud_organizations`, `list_projects`, `get_campaign_calendar`, `estimate_eql_cost`, `execute_analytics_eql` |

`search_discovery_catalog_jobs` is usually not listed directly: find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Do the same for any other tool you can't see. Check each tool's parameters before calling it. Use read tools only: `search_tools` also returns write tools; never call them.

### Agree the scope

Ask, unless the user has already said:

- **Which products:** Discovery only, Engagement only, or both. If the user names only a Discovery account, do Discovery only and offer the Marketing section. If they name only an Engagement project, do Engagement only.
- **Which account and site** (Discovery) and **which project** (Engagement).

### Choose the week

- **Default: the last 7 days of available data** (`days=7`), compared with the 7 days before. Discovery data usually ends a day or two before today, so on a Monday the last full Monday-to-Sunday week often isn't complete yet. Read the actual dates from `get_discovery_trend` (step 2) and print them in the title.
- If the user wants a calendar week and it's complete, pass `start_date` and `end_date` (`YYYY-MM-DD`) to every Discovery call instead. The comparison is the 7 days before.
- **Use the same window for every call.** The window changes the story: in testing, the last 7 days showed revenue −3.7%, while the Monday-to-Sunday week that overlapped it showed −0.1%.

### Rules for calling the tools

- **One call at a time.** Discovery and Engagement each allow about 3 requests per second per user, shared with everything else the user runs; EQL allows about one query every 3 seconds. On HTTP 429 or 500, wait a few seconds and retry once with default parameters.
- **About 17 Discovery calls and 3–5 Engagement calls** make a full briefing. Tell the user before you start if they asked for both products.
- **Large tables are saved to files.** A 100-row table is 60,000 to 90,000 characters. Keep the files for the script in step 3, or extract only the fields you need.
- **Personal data:** never repeat email addresses or names from `lastModifiedBy`, `edited_by` or `user` fields, or anything from customer records. Use only aggregate Engagement queries.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/briefing_numbers.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the account and project

**Discovery:** call `list_discovery_accounts` (filter for the account the user named; ask if it's ambiguous), then `list_discovery_sites`. If there's more than one site, ask which one, and pass its `site_group_id`, `domain_key` and `view_id` to every reporting call. If there are **no sites**, leave those out to report at account level, and say so.

**Engagement:** call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and ask. Never guess.

### 2. Headline KPIs (Discovery)

Make these calls with the same window, one at a time, and save each response:

1. `get_discovery_overall_performance`
2. `get_discovery_search_performance`
3. `get_discovery_category_performance`
4. `get_discovery_overall_performance` with `device_type="desktop"`, then `"mobile"`, then `"tablet"`
5. `get_discovery_trend` with `metric="revenue"`: for the dates (`cdate`), and to spot missing or $0 days, which mean a data gap.

Each card has `current`, `previous` and `trends`. Work from the raw counts: RPV = revenue ÷ visits, conversion = conversions ÷ visits, AOV = revenue ÷ conversions. "Conversions" are orders.

- The device cards add up to the overall card.
- Search and category don't: a visit can include both. Show **other** = overall − search − category as approximate.
- Show conversion changes in **percentage points**, and the others as percentages.

### 3. Top searches and categories, issues and movers (Discovery)

Make these calls with the same window, one at a time:

| Table | Call |
|---|---|
| Queries | `get_discovery_query_performance` with `sort="browse_sessions"`, `page_size=100` |
| Categories | `get_discovery_category_performance_table` with `sort="revenue"`, `page_size=100` |
| Products | `get_discovery_product_performance_table` with `sort="revenue"`, `page_size=100` |
| Brands | `get_discovery_brand_performance` with `sort="revenue"`, `page_size=100`. If the window is 30 days rather than a week, work out brand changes from the product table instead: with `days=30` this tool has returned a wrong previous period |
| Dead-end searches | `get_discovery_query_performance` with `filter_preset="no_search_results"`, then `"no_revenue"`, each with `sort="browse_sessions"`, `page_size=20`. You need both presets: `no_search_results` misses many dead ends. |

Then run:

```bash
python3 <this skill's folder>/scripts/briefing_numbers.py --overall overall.json --search search.json --category category.json --device desktop=desktop.json --device mobile=mobile.json --device tablet=tablet.json --queries queries.json --categories categories.json --products products.json --brands brands.json --dead-ends no_results.json,no_revenue.json [--min-visits 100] [--min-sessions 30] [--top 3] [--list-top 10] [--issue-top 5]
```

It prints the KPI table values, the top and issue lists, and the movers. If any value was missing or `NA`, `missing_values` lists it (counted as 0): say so next to the affected numbers.

**Top and issues** (`top_and_issues` in the output), for searches and for categories:

- **Top:** the 10 with the most revenue this week, with revenue change, conversion and bounce.
- **Issues:** rows with enough traffic that are judged against the **median of the 20 highest-traffic rows** (like with like). A row is flagged for:
  - conversion below 75% of that median;
  - bounce more than 25% above it, and at least 10 points higher;
  - no revenue;
  - revenue down more than 25% on last week.

  Issues are ranked by **revenue at stake**: traffic × (typical conversion − its conversion) × order value, or the revenue lost since last week if that's bigger. It's an upper bound for the week, not a forecast.
- **Dead ends** (searches only): searches with traffic but no product views. Most return no results. They're summarised on one line (count, sessions, revenue at stake at the typical revenue per visit), because each is small but together they add up.

**Movers:**

- **Queries** use the `discovery-trending-searches` method: each query's sessions are compared with what overall search growth predicts, and ranked by a volume-weighted trend score, so a big query growing 10% outranks a tiny one growing 200%. It also lists the queries whose revenue moved most.
- **Categories, products and brands** are ranked by the change in revenue (money, not percent), ignoring rows with fewer than `--min-visits` visits in both weeks.

If you can't run scripts, do the same by hand. **Never sort the tables by `change_*`:** that puts tiny rows first.

Pick 2–3 movers per type for the briefing. Prefer ones that tell a story together (for example "diamond" searches and the rings category both falling). Note any rising query with poor conversion or high bounce: that's an opportunity.

For each issue, name the skill that fixes it:

| Issue | Skill |
|---|---|
| Search with low conversion or high bounce | `discovery-query-diagnosis` |
| Dead-end searches | `discovery-zero-results-triage` |
| Category with low conversion or high bounce | `discovery-category-health` |
| Products behind a category's problem | `product-opportunity-finder` |

Watch for repeated patterns. In testing, several categories at about 63% bounce and 10% conversion (bracelets, a Valentine's collection, summer sale, activewear) pointed to a shared page or template problem rather than separate merchandising problems. Say so when you see it.

### 4. Marketing (Engagement, optional)

Use the method of the `engagement-campaign-digest` skill, cut down to highlights. Read [references/marketing-section.md](references/marketing-section.md) for the queries.

1. Work out the same two 7-day windows as Unix timestamps (seconds) and ISO dates ending in `Z`.
2. Call `get_campaign_calendar` for this week. Drop entries with `status` `draft` or `inactive`. Note the sends and any `failed` reach.
3. Run the email status mix for this week and last week (estimate the cost first, then run; one query every 3 seconds). Add SMS only if the calendar shows SMS sends.
4. Report sends, delivery rate, click rate and any flag (bounce over 2% of sends, unsubscribes over 0.5% of delivered). If there's no campaign data, say "No campaign sends recorded this week".

For per-campaign rankings, offer the `engagement-campaign-digest` skill.

### 5. Health alerts

Use the method of the `data-feed-health` skill, cut down to alerts:

1. `get_pixel_health_status` with `period_hours=24`, then `168`. Flag a core pixel type (`product-pageview`, `category-pageview`, `search-pageview`, `conversion-pageview`, `atc-event`, `search-event`) that has an issue rate of 20% or more, no events, or a 24-hour count more than 50% below its 7-day daily average. Name the top issue key in plain words (for example `catalogs_required`: the page doesn't send the catalog name).
2. `search_discovery_catalogs`, then `search_discovery_catalog_jobs` (via `call_tool`) with `catalog_name`, `account_name` and `limit=50`. Flag a failed latest product feed or index job, no successful one for more than 48 hours, or a product count drop of 10% or more. Check each job's `status` yourself; the filter is ignored.
3. Note missing or $0 days from the trend in step 2.

Show **one line per problem**, or "No new issues" if everything is healthy. A problem that was there last week too is still worth one line, marked "ongoing". For the full check, offer the `data-feed-health` skill.

### 6. Three things to do this week

Read [references/action-playbook.md](references/action-playbook.md). Pick the **three** actions with the most money at stake, using the evidence from steps 2–5. The search and category issue lists from step 3 are usually the best source. Each one must:

- say **what to do** in one line, naming the query, category, product, brand or campaign;
- give the **evidence** in a few words ("'diamond' −$35k, AOV $354 → $341");
- name the **skill** that does it (for example `discovery-query-diagnosis`).

Put a data problem first if one makes the numbers unreliable. If revenue moved by more than about 5%, or the user will want to know why, make one of the three "find out why" with the `revenue-anomaly-explainer` skill.

## Output

Keep it to about 55 lines. Leave out sections the user didn't ask for.

```
## Weekly briefing: <account/site and/or project>, <dates> vs <dates>

**Headline:** <one sentence: the main story of the week>

| | Revenue | RPV | Conversion | AOV |
|---|---|---|---|---|
| Overall | $7.63M (−3.7%) | $73.71 (−0.8%) | 50.6% (+0.1 pt) | $145.75 (−0.9%) |
| Search | ... | ... | ... | ... |
| Category | ... | ... | ... | ... |
| Other* | $0.87M (−8.1%) | — | — | — |
| Desktop / Mobile / Tablet | −3.9% / −5.5% / −1.4% revenue | ... | ... | ... |
*Overall minus search and category; approximate.

**Top searches:** diamond $392k · dress $200k · mens pants $149k · black dress $146k · bags $139k … (top 10)
**Searches with issues:**
- tshirt: conversion 11.5% vs 21.3% typical, bounce 60% vs 26%. Up to $22k this week → `discovery-query-diagnosis`
- ... (top 5)
- 8 dead-end searches (swim trunks, sports bra, capris…): 1,811 sessions, up to $45k → `discovery-zero-results-triage`

**Top categories:** pacific specials $134k · rings $130k · necklaces $130k · bracelets $128k … (top 10)
**Categories with issues:**
- bracelets: conversion 10.5% vs 17.0% typical, bounce 63% vs 26%. Up to $79k → `discovery-category-health`
- ... (top 5)

**Top movers**
- Queries: ↑ <query> (+x% vs baseline) · ↓ <query> (−$)
- Categories: ↑ ... · ↓ ...
- Products: ↑ ... · ↓ ...
- Brands: ↑ ... · ↓ ...

**Marketing:** <sends, delivery, clicks, flags; or "not included">

**Health:** <RED/AMBER line per problem, or "No new issues">

### 3 things to do this week
1. **<action>**: <evidence>. → `<skill>`
2. ...
3. ...
```

Use the status words RED and AMBER, not colour alone. Round money to three significant figures. Offer to run any of the three linked skills.

## Safety

This skill is **read-only**. It never creates, changes or deletes anything in Discovery or Engagement, never re-runs jobs, and never sends anything.

- Engagement: use only aggregate queries. Never call `list_customers`, `get_customer_properties`, `list_customer_events` or `list_customers_in_segment`. Estimate every EQL query first, and don't run one that scores `very_high`.
- Don't repeat email addresses, names, user IDs, cookies or IP addresses from rule lists, the campaign calendar or pixel samples.
- If the user asks to act on a recommendation, hand over to the linked skill, which confirms every change.
