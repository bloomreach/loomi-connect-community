---
name: facet-optimizer
description: Reviews the filters (facets) on Bloomreach Discovery search and category pages with Loomi Connect, for the top queries and categories. It finds junk facets (too many values, empty, unbucketed numbers, internal fields), useful facets that are missing or buried for a product type (size, colour, fit, price, gender), and facet values that need merging or tidying, and it reviews the existing global, search and category facet rules. It recommends boost, bury, hide or always-show changes per query or category type, without making them. Use when the user asks about facets, filters, refinements or faceted navigation, which filters to show, why a filter is missing or messy, or how to improve filtering to lift conversion.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery).
metadata:
  author: bloomreach
  version: "0.1.4"
  products: discovery
  access: read-only
---

# Facet optimizer

## What this does

Shoppers on a big results page narrow it down with filters. If the filters they need (size, colour, price) are missing or buried under junk (a rating filter with 200 raw values, an internal "cluster" code, an empty filter), they scroll, give up or bounce.

This skill looks at the filters shoppers actually see on the account's highest-traffic searches and category pages, checks them against the attributes the catalog could offer and the facet rules in place, and returns specific **boost, bury, hide and always-show** recommendations per query or category type, plus value clean-ups.

This skill only reviews and recommends. It never creates, changes or deletes anything.

Related skills: `discovery-category-health` covers category ranking and merchandising (which products show), and `autosuggest-audit` can send shoppers to the bare product query, where good filters matter most.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Account and site | `list_discovery_accounts`, `list_discovery_sites` |
| Top searches and categories | `get_discovery_query_performance`, `get_discovery_category_performance_table` |
| The filters shoppers see | `search_discovery_product_grid_insights` |
| Facet rules | `list_facets_global`, `list_site_search_facets`, `list_category_facets`, `get_facet_rule` |
| Facetable attributes | `list_facet_attributes` (usually not listed: find it with `search_tools`, run it with `call_tool`) |

If any tool isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Use read tools only: `search_tools` also returns write tools; never call them. Don't rely on reading the `loomi://guides/*` resources; not every client can.

You need the account, and optionally a site and a date range (default: the last 30 days).

### Rules for calling the tools

- **Make every call one at a time.** Discovery allows about 3 requests per second per user, shared with anything else the user is running. Parallel product grid calls can return HTTP 500. On a 429 or a 500, wait 2–5 seconds and retry once with default parameters.
- **Keep product grid responses small, but keep facets on.** This skill needs `data.facet_counts.facets`, so **don't** pass `extra_params={"facet": "false"}`. Pass `fl="pid,title"` and `rows=1`. A response is then 25,000–60,000 characters; most of it is the debug block, and the brand facet alone can list about 200 values. Don't pass `simple_debug=false`; it returns HTTP 500.
- **If the client saves a response to a file**, run `python3 <this skill's folder>/scripts/facet_summary.py <file> [<file> ...] --attributes <saved list_facet_attributes response>`. It prints each facet with its value count, top values, coverage and flags, and the facet rules that applied. Otherwise read only `data.response.numFound`, `data.facet_counts.facets` and the `ruleType: "facet"` entries in `data.debug["customizations.explain"]`.
- **Personal data:** `get_facet_rule` returns the name or email address of the person who last edited the rule (`user`). Never repeat it.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/facet_summary.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the account and site

1. Call `list_discovery_accounts`. Filter for the account the user named, and ask if it's still ambiguous.
2. Call `list_discovery_sites`. If the account has sites, ask which to review and pass its `site_group_id`.
3. If the account has **no sites**, work at account level. For the product grid, try the account name as the `domain_key`. Tell the user you've done this.

### 2. Pick what to review

1. Call `get_discovery_query_performance` with `filter_preset="top_searched"`, `page_size=20`.
2. Call `get_discovery_category_performance_table` with `filter_preset="top_categories"`, `page_size=20`. (Don't use `filter_preset="lowest_converting"`; it returns no rows.)

Pick **6–10 pages**: the top 4–5 queries by sessions, covering **different product types** (for apparel: a bottoms query, a dress query, a tops query, an accessory query), plus the top 2–3 real categories and **1–2 high-traffic categories that convert well below the others**. Skip dynamic and collection categories (IDs starting `brg_dyn_`) unless the user asks for them. Note each page's sessions, conversion rate and bounce rate.

### 3. Read the facet rules and the attributes

Make these calls one at a time:

1. `list_facets_global`, `list_site_search_facets` and `list_category_facets`. The lists show IDs and scope, not the settings.
2. `get_facet_rule` for each rule that applies to a page you picked, plus the global rule. Its `customizationItems` holds `boosted_facets` and `buried_facets` (facet → position), `always_included_facets`, `excluded_facets`, `aliases_facets` (renames) and `value_configs_facets` (merges, value boosts and price ranges). `audiences` shows audience targeting; the lists show `audienceName: null` even when a rule targets an audience.
3. `list_facet_attributes` via `call_tool`, with `limit=200`. It lists every attribute that can be a facet, with its type (`STR`, `NUM`, `HIERARCHY`) and level (`PARENT` or `CHILD`, meaning variant-level such as size).

You can also see which facet rules applied to a page in the product grid's `customizations.explain` (`ruleType: "facet"`), without extra calls.

### 4. Look at the filters on each page

For each page you picked, call `search_discovery_product_grid_insights` once:

- a search: `query=<query>`, `fl="pid,title"`, `rows=1`;
- a category: `search_by="category"`, `query=<category ID>`, `fl="pid,title"`, `rows=1`.

`data.facet_counts.facets` lists the facets in the order the page returns them, which reflects the facet rules. For each facet record: its position, the number of values, the top values, and how many of the results the values cover. Then run the checks below. Read [references/facet-checks.md](references/facet-checks.md) for the evidence each one needs and the change to recommend.

| Check | How to spot it |
|---|---|
| **Empty** | a facet with no values, often because a rule forces it to always show (in testing `color_groups` was empty on every page) |
| **Too many values / unbucketed number** | more than about 30 values; a numeric facet listing raw values ("rating" with 43 values on 43 dresses, about 200 on "pants") |
| **Placeholder value** | one numeric value covers a large share of results (rating "1.0" on 27–37% of products: a default, not a real rating) |
| **Internal-looking** | names or values that mean nothing to shoppers ("cluster" with values "c18", "c69"); facetable attributes such as `margin` or `omni_score_*` that must never be shown |
| **Single value / no narrowing** | one value only ("gender: female" on women's dresses, "brand: Pacific" on a one-brand category), or a value on almost every result ("Under $200" on 2,677 of 2,680) |
| **Missing for the product type** | an attribute shoppers need for this type exists in `list_facet_attributes` but isn't shown: size on clothing, price everywhere, gender on mixed-gender queries ("pants" spans men and women) |
| **Buried** | a key facet appears late (size 5th behind an empty facet; last on "jeans") |
| **Low coverage** | the facet covers few results (size on 52 of 1,170 jeans): the catalog data is missing, not the rule |
| **Values to merge or tidy** | case, spacing or spelling variants ("gray" 665 / "grey" 33; "Pacific" / "Pacific "; "Denium"), raw labels ("true"/"false" on an on-sale filter), test or campaign values in the category filter ("test_yellow_color_products", "marketing campaign XYZ") |
| **Rule problems** | rules that boost a junk facet ("rating" boosted to position 2 on dresses), always-show empty facets, value merges for values that never occur on that page, price ranges configured but no price facet shown |

### 5. Decide what to recommend

Group recommendations by **scope**, from widest to narrowest, so one change fixes many pages:

1. **Global** (all search and category pages): hide internal facets; stop always-showing empty facets; merge and tidy values.
2. **Per product type** (several queries or categories that share a type, e.g. all bottoms): boost size and fit; always show price; show gender on mixed queries.
3. **Per query or category**: special cases.

For each recommendation give: the scope (global, the query, or the category ID and name); the action (**boost** to position N, **bury**, **hide**, **always show**, or **merge** / **rename** values); the facet; the evidence; and the sessions on the pages it affects.

Facet changes rarely have a reliable revenue estimate. Report the sessions affected, and the conversion gap where a page converts well below similar pages, as context, not as a forecast. Recommend an **A/B test** for big changes to high-traffic pages.

Note what the API can and can't do. The facet-rule write tools support boost, bury, hide (exclude), always-show and audience targeting. Their own descriptions say that **range buckets, value merging, value renaming and per-value ordering are not available through the API** and must be set in the Discovery dashboard. Say so next to those recommendations.

## Output

```
## Facet review: <account/site>, <date range>

**Headline:** <one sentence: the most valuable change>

**Reviewed:** <n> pages (<queries and categories>), covering <n> sessions. <n> facet rules (<global/search/category>). <n> facetable attributes.

### Global changes
| # | Action | Facet | Evidence | Pages affected |
|---|---|---|---|---|

### By product type
| Product type (pages) | Show and order | Hide or bury | Evidence |
|---|---|---|---|

### Values to merge or tidy (dashboard)
- <facet>: <variants> → <one value>

### Catalog data gaps (not fixable with rules)
- <facet>: <coverage>; <which products lack it>

### Existing rules to change
- Rule <id> (<scope>): <what to change and why>

**Next steps:** up to three
```

## Safety

This skill is **read-only**. It never creates, changes or deletes facet rules or anything else.

- **Never repeat** `auth_key` URLs from grid debug output (`feUrl`, `sqApiUrl`), editor emails (`lastModifiedBy` in synonyms), or internal commercial fields such as `margin` or `cost`.

If the user asks to apply a change, hand it off. This skill never uses a write tool, even if asked.

1. Give the exact change for them to make in the Bloomreach Discovery dashboard: the rule (new or existing ID), its scope (global, query, category ID), the facets and positions for each action, any audience, and whether it's enabled. Suggest creating new rules disabled first.
2. Warn them that **Discovery changes go live immediately**, that deletes can't be undone, and that changes are blocked while an A/B test runs.
3. Point out that a global rule affects every search and category page.
4. Once they've made the change, re-run the product grid for an affected page and check the facet order.
