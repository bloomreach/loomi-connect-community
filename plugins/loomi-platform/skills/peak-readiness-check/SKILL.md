---
name: peak-readiness-check
description: Runs a go/no-go readiness check for a sale, launch or peak trading event such as Black Friday across Bloomreach Discovery and Engagement using Loomi Connect, and returns a red, amber and green checklist with blockers first and an owner for each fix. It checks tracking and feed freshness, merchandising rules, redirects and banners scheduled for the event window, A/B tests that would block changes, event landing pages and category grids, search results for event queries, campaign calendar sends, clashes, segments, frequency caps and on-site weblayers. Use when the user asks if they are ready for Black Friday, Cyber Monday, a sale, a launch or a peak date, wants a pre-event checklist or go/no-go, or asks what could go wrong on the day.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery and Engagement; either one alone gives a partial check).
metadata:
  author: bloomreach
  version: "0.1.4"
  products: discovery,engagement
  access: read-only
---

# Peak readiness check

## What this does

Answers "are we ready for <event> on <date>?" with one checklist. Every item gets a status (RED, AMBER, GREEN, NOT CHECKED), one line of evidence, the fix, and the **owner type** who usually makes the fix. Blockers come first.

It covers five areas:

1. **Data:** Discovery pixel health and catalog feed freshness.
2. **Merchandising:** ranking, media (banner) and redirect rules for the event window; rules that expire mid-event; running A/B tests that block changes; event dynamic categories and landing pages that are empty or thin; top category grids.
3. **Search:** the event's likely queries ("black friday", "sale", "gifts for him") return relevant results or redirect.
4. **Marketing:** event sends on the Engagement campaign calendar, clashes between them, target segments and frequency caps.
5. **On-site engagement:** Engagement banners and weblayers for the event are active and scheduled.

It only reads. It never schedules, enables, edits or sends anything.

## Before you start

This skill uses these Loomi Connect tools:

| Area | Tools |
|---|---|
| Discovery account | `list_discovery_accounts`, `list_discovery_sites` |
| Data | `get_pixel_health_status`, `search_discovery_catalogs`, `search_discovery_catalog_jobs` |
| Merchandising | `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `list_site_search_media_rules`, `list_category_media_rules`, `list_global_media_rules`, `search_redirects`, `search_discovery_experiments`, `search_dynamic_categories`, `get_discovery_category_performance_table` |
| Search and previews | `search_discovery_product_grid_insights`, `get_discovery_query_performance` |
| Engagement project | `list_cloud_organizations`, `list_projects` |
| Marketing | `get_campaign_calendar`, `search_scenarios`, `search_scenario_nodes`, `search_email_campaigns`, `search_segmentations`, `get_frequency_policies`, `estimate_eql_cost`, `execute_analytics_eql` |
| On-site | `search_banners`, `search_in_app_messages` |

Several of these are not listed directly (`search_discovery_catalog_jobs`, `list_site_search_media_rules`, `list_category_media_rules`, `search_scenario_nodes`, `get_frequency_policies`). Find them with the Loomi Connect `search_tools` tool and run them with `call_tool`. Check each tool's parameters before calling it. Only ever use read tools: `search_tools` also returns write tools; never call them.

### Ask first

- **The event:** name, **start and end date and time**, and timezone. Without dates the check is meaningless. If the user gives only a day ("Black Friday"), confirm the window (for example 27 Nov 00:00 to 1 Dec 23:59, store timezone).
- **The scope:** Discovery account and site; Engagement organisation and project. If there's more than one of any of these, **list them and ask. Never guess.**
- **Event vocabulary:** the queries, category names, rule names and campaign names the team uses for this event ("BF", "Cyber", "Holiday 26"). Offer the defaults in [references/event-queries.md](references/event-queries.md) and add the user's own.
- **Landing pages:** the categories or dynamic categories the event will link to.

### Rules for calling the tools

- **One call at a time**, including list calls. Discovery and Engagement each allow about 3 requests per second per user, and EQL allows about one query every 3 seconds, shared with everyone on the same Engagement instance. On HTTP 429, wait 3–10 seconds and retry once. On HTTP 500 from the product grid, wait and retry once with default parameters.
- **Keep product grid calls small:** `fl="pid,title,price"`, `rows` of 5–10, and `extra_params={"facet":"false"}`. Responses still carry a large debug block. If the client saves one to a file, read only `data.response.numFound`, `data.response.docs[].title`, `data.autoCorrectQuery`, `data["relaxed.query"]`, `data.metadata.query.modification` and `data.debug["synonym.explain"].queryIntents`.
- **Don't use the `duration` filter on Discovery rule lists.** It returned HTTP 400 in testing. List with `limit=100` (page if `meta.pagination.total` is higher) and filter by date yourself.
- **Never read individual customers.** Segment sizes come from aggregate counts only. Don't call `list_customers`, `list_customers_in_segment`, `get_customer_properties` or `list_customer_events`.
- **Don't fetch banner or scenario details you don't need.** Banner details include the full HTML and script, and webhook nodes can contain personal data. Never quote template or script content.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/check_rule_windows.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

Work through the areas in order. If the user only has Discovery or only Engagement, run the parts you can and mark the rest NOT CHECKED.

### 1. Resolve the scope

1. `list_discovery_accounts`, then `list_discovery_sites`. If the account has **no sites**, work at account level: leave out `site_group_id`, and use the account name as the product grid `domain_key`. Say so.
2. `list_cloud_organizations`, then `list_projects`. Confirm the **production** project with the user: readiness is about what shoppers will see. Read only configuration and aggregate counts there.
3. Convert the event window to Unix **milliseconds** (Discovery rules use `startedAt`/`endedAt` in ms) and **seconds** (Engagement calendar uses `from_ts`/`to_ts` in seconds).

### 2. Data

Use the method of the `data-feed-health` skill, in short form:

1. `get_pixel_health_status` with `period_hours=24`. Any **core** type (`product-pageview`, `category-pageview`, `search-pageview`, `conversion-pageview`, `atc-event`, `search-event`) at 20% issues or more is **RED**: event-day reports and personalisation depend on it. 1–20% is AMBER.
2. `search_discovery_catalog_jobs` (via `call_tool`) with `catalog_name`, `account_name` and `limit=20`. Check `status` on each job yourself. The latest product feed (`type: "feed"`, `properties.feed_data_type: "products"`) or `index` job failed, or none succeeded in 48 hours: **RED**. A success with a `status_message` warning (for example null values): AMBER.
3. Ask, or note as a check for the team: **will the feed run more often during the event?** Price and stock change fast on peak days. A daily feed is AMBER for a flash sale.

Owner types: pixel → **web developers**; feed → **feed or catalog owner**.

### 3. Merchandising rules for the window

1. List all six rule types and `search_redirects`, one call at a time, `limit=100`. Save each response.
2. If you can run scripts:

   ```
   python3 <this skill's folder>/scripts/check_rule_windows.py --rules <file> [--rules <file> ...] --start <ISO start> --end <ISO end> [--keywords "black friday,bf,cyber,sale"] [--experiments <experiments file>]
   ```

   Otherwise apply the checks in [references/readiness-checks.md](references/readiness-checks.md) by hand. The checks:
   - **Event rule starts late or ends early:** a rule whose name or query matches the event vocabulary, but whose `startedAt` is after the event start or `endedAt` before the event end. RED if enabled and it's the only event rule for that query or category; AMBER otherwise.
   - **Expires mid-event:** any enabled rule with an `endedAt` inside the window. AMBER (RED if it's an event rule).
   - **Event rule disabled:** matches the event vocabulary but `enabled: false`. RED if it's the only one.
   - **No end date on an event rule:** `durationTag: "unscheduled"`. AMBER: it will run past the event unless someone remembers.
   - **Leftover rules from last year's event:** `durationTag: "expired"` but still enabled. AMBER (clutter, and easy to re-enable by mistake).
   - **No event rules at all:** if nothing matches the vocabulary, that's AMBER (RED if the user says rules were planned). Confirm the vocabulary with the user before reporting this.
   - Use `durationTag` and the timestamps, **not** `syncStatus`.
3. `search_discovery_experiments` with `experiment_statuses="RUNNING"`. A running test **blocks changes** to rules in its scope until it ends. A test running into the event window is **RED** if event rules still need changes, AMBER otherwise. Get each test's end date with `experiment_id`.
4. `q` on rule lists matches rule **names** as well as queries ("black friday" found a rule named "Skirts black Friday" on the query "skirts"). Use it to find event rules quickly, but still filter the full list by date.

Owner type: **merchandiser**. Changes during a running A/B test need the **test owner**.

### 4. Landing pages and category grids

1. `search_dynamic_categories` lists dynamic categories. Note the event ones by name. **The list and the by-ID view don't show membership**: `productIds` is empty for rule-based categories. Preview each event category instead:
   `search_discovery_product_grid_insights` with `search_by="category"`, `query=<categoryId>` (for example `brg_dyn_…`), `rows=10`.
   - `numFound` 0: **RED** (an empty landing page).
   - `numFound` under about 24 (one page): **AMBER** (a thin page; check the conditions with `category_id`).
   - Look at the top 10 titles: do they fit the event? Duplicates or obvious misfits: AMBER.
2. `get_discovery_category_performance_table` with `days=30`, sorted by visits, `page_size=10`. Preview the top 3–5 categories the same way (`search_by="category"`, `query=<cat_id>`). Flag empty or very thin grids, and check whether event media rules attach to these category IDs.
3. If the event links to a page the user names, preview that one too.

Owner types: empty dynamic category → **merchandiser** (conditions) or **feed owner** (missing attributes such as a sale flag); thin grid → **merchandiser** or **buyer** (stock).

### 5. Search for the event's queries

For each event query (default list in [references/event-queries.md](references/event-queries.md), plus the user's), one at a time:

1. `search_redirects` with `q=<query>`. A redirect to the event page is the cleanest answer for generic event queries. Check its dates the same way as rules.
2. If not redirected, `search_discovery_product_grid_insights` with the query, `rows=10`. Read:
   - `numFound`;
   - `data.autoCorrectQuery` and `data.metadata.query.modification`: **`autoCorrectQuery`** means the engine rewrote the query (in testing, "black friday" became "black frisky" and returned black clothing). **`relaxedQuery`** means it dropped words ("gifts for him" relaxed to "gifts");
   - the top titles: relevant to what the shopper meant?
3. Rate each query:
   - **RED:** 0 results; or the query is spell-corrected into something else; or results are clearly off-topic for a query you expect heavy event traffic on.
   - **AMBER:** relaxed, or a very broad match (for example, a quarter of the catalog for "sale") with no rule or redirect shaping it; or no products flagged as on sale at the top.
   - **GREEN:** redirected to a live event page, or relevant results with event rules applied.
4. Optional: `get_discovery_query_performance` with `search=<word>` and last year's event dates (`start_date`, `end_date`) shows what people actually searched. Redirected searches never appear there, and a demo or new account may show nothing.

Owner types: missing redirect, synonym or rule → **merchandiser** or **search admin**; spell-correction rewriting an event term → **search admin** (add it as a synonym or keyword so it isn't corrected).

### 6. Marketing sends (Engagement)

Use the method of the `engagement-send-collision-check` skill, scoped to the event window plus 3 days either side:

1. `get_campaign_calendar` **one week at a time** (wider windows can time out). Separate customer messages (email, SMS, push) from webhooks and internal reports. Drafts appear with planned times: list them separately.
2. **Event sends exist:** at least one active or scheduled customer send per key event day. None at all: **RED** (unless the user confirms marketing for this event runs elsewhere). Event sends still in `draft`: AMBER (they won't go unless someone starts them).
3. **Clashes:** run `find_collisions.py` from the collision-check skill if installed, or apply its rules: same channel to overlapping audiences within 24 hours, email and SMS within 4 hours, 3 or more sends on one day. Clashes on event days are AMBER; same-audience clashes with no frequency cap are RED.
4. **Always-on flows:** `search_scenarios` with `status="active"` and `trigger_types=["onevent","ondateattribute","onapi","onapi-interest","oncatalog"]`. These add to event-day volume. Note abandoned-cart and browse flows: missing ones are a revenue gap on the busiest days (hand off to `funnel-leak-finder`).
5. **Target segments:** for each event send, find its segmentation (send node → condition → `customer_filter`, or the `used_by` shortcut in `search_segmentations`). A referenced segmentation that is missing or archived is **RED**. Size each event segment with an aggregate count (the `engagement-segment-builder` method; `estimate_eql_cost` first, never run `very_high`). Zero or tiny: RED; much smaller than last event: AMBER.
6. **Frequency caps:** `get_frequency_policies` (via `call_tool`). Read only names, rules and `default_policy_id`. Default `unlimited-policy` with several event sends: AMBER. A strict cap can also **silently drop** a key event send when an earlier one used the allowance: note which send would lose.

Owner types: missing or draft sends, clashes → **CRM or email marketer**; segments → **CRM analyst**; frequency policy → **Engagement admin**.

### 7. On-site engagement (Engagement)

1. `search_banners` with `status="active"`, then with `serving_status="before_schedule"` (active but starts later) and `serving_status="after_schedule"` (active but already ended). Match names and tags against the event vocabulary.
   - Event weblayer active and scheduled to start before the event: GREEN.
   - Event weblayer exists but `inactive` or still a draft: AMBER (RED on the day).
   - Event weblayer already `after_schedule`: RED.
   - No event weblayer and the user expects one: AMBER.
2. Fetch a banner by `banner_id` only to read its schedule or targeting if needed; ignore the HTML and script.
3. Optional: `search_in_app_messages` the same way for app campaigns.

Owner type: **CRM or web marketer**.

### 8. Build the checklist

Collect every item as one row: area, check, status, evidence, fix, owner type, and whether it's a blocker (RED). If you can run scripts, save the rows as JSON and run:

```
python3 <this skill's folder>/scripts/render_checklist.py items.json --event "<name>" --window "<start> to <end>"
```

It sorts blockers first, then AMBER by area, and prints the verdict. Otherwise sort by hand.

**Verdict rules:**
- **NO-GO:** any RED in data, search for top event queries, landing pages, or "no event sends".
- **GO WITH FIXES:** REDs only in lower-impact items, or AMBERs only.
- **INCOMPLETE:** nothing RED or AMBER, but some items are NOT CHECKED. Never call it GO until they're checked.
- **GO:** all GREEN, or AMBERs the user has accepted.

Say how many days remain and which fixes need a lead time (feed changes, new segments, template approvals) versus same-day fixes (rule dates, redirects).

## Output

```
## Peak readiness: <event>, <start> to <end> (<timezone>)
Checked <date>; <n> days to go. Scope: <Discovery account/site>, <Engagement project>.

**Verdict:** NO-GO / GO WITH FIXES / INCOMPLETE / GO: <one sentence: the biggest blocker and the fix>

### Blockers (fix before the event)
| # | Area | Check | Evidence | Fix | Owner |
|---|---|---|---|---|---|

### Amber (fix or accept)
| # | Area | Check | Evidence | Fix | Owner |

### Green
<one line per area: what passed>

**Not checked:** <areas or items you couldn't see, and why>
**Lead times:** <fixes that need days, not minutes>
```

Use the words RED, AMBER, GREEN and NOT CHECKED, not colour alone. Keep it under about 40 lines; offer detail on any item.

## Safety

This skill is **read-only**. It never creates, schedules, enables, disables or deletes rules, redirects, categories, experiments, campaigns, scenarios, segments, banners or policies, and never sends anything.

- Discovery changes go live immediately, and changes are blocked during a running A/B test. If the user asks you to fix something, describe the exact change for them to make, or hand off to a skill that writes, which must show the change and wait for an explicit "yes".
- Use aggregate counts only. Never read or quote individual customers, and never repeat template, script or webhook content.
- **Never repeat** `auth_key` URLs from grid debug output (`feUrl`, `sqApiUrl`), editor emails (`lastModifiedBy` in synonyms), or internal commercial fields such as `margin` or `cost`.
