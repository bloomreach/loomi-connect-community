---
name: product-opportunity-finder
description: Sorts every product in a Bloomreach Discovery account into actionable groups using Loomi Connect product performance data and the live product grid - products whose page needs fixing (many views, few add-to-carts), hidden gems to boost (convert well, seen little), declining winners, dead weight with no views, and over-exposed products to bury - with a recommended action, the revenue at stake worked out transparently, and the skill to hand off to. Use when a merchandiser or ecommerce manager asks which products to boost or bury, where the product-level revenue opportunities are, which best sellers are slipping, which products get views but don't sell, or wants a product opportunity or assortment review.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery).
metadata:
  author: bloomreach
  version: "0.1.4"
  products: discovery
  access: read-only
---

# Product opportunity finder

## What this does

Takes the whole product performance report for an account, sorts products into five groups a merchandiser can act on, checks where the most valuable ones rank on their main search queries, and returns a prioritised list. Each product gets a recommended action, the revenue at stake with the working shown, and the skill to use next.

| Group | Signal | Usual action |
|---|---|---|
| **Fix the product page** | many views, add-to-cart rate well below the typical product | Check price, images, description, sizes and stock. Not a search fix |
| **Hidden gems** | few views, conversion well above the typical product | Boost on their main queries and categories (A/B test) |
| **Declining winners** | a top earner last period, now falling behind the account's trend | Find out whether it lost visibility (ranking) or conversion (price, stock) |
| **Dead weight** | no views at all | Bury, clear, or fix the product data so it can be found |
| **Over-exposed** | many views, add-to-cart normal, conversion well below typical | Bury or move down (A/B test), or check price and stock |

This skill only analyses and recommends. It never changes anything.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Account and site | `list_discovery_accounts`, `list_discovery_sites` |
| Product metrics | `get_discovery_products_overview`, `get_discovery_product_performance_table` |
| Main queries for a product | `get_discovery_query_performance` |
| Where products rank | `search_discovery_product_grid_insights` |

If one of them isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Use read tools only: `search_tools` also returns write tools; never call them. Check each tool's parameters before calling it.

You need the account, and optionally a site and a date range. The default is the last 30 days.

### Rules for calling the tools

- **Make calls one at a time.** Discovery allows 3 requests per second, and other work may share the limit. Parallel product grid calls can return HTTP 500. On a 429 or 500, wait a few seconds and retry once with default parameters.
- **Expect large responses.** The full product table is about 900 characters per product (6,600 products is about 6 million characters), and a product grid row carries a long debug explanation (24 rows can exceed 600,000 characters). The client usually saves them to a file. Don't read them into the conversation: pass the files to the scripts below, or extract only the fields you need.
- **Keep product grid requests small.** Always pass `fl` (for example `pid,title,brand,price`). Pass `extra_params={"facet":"false"}` unless you need the brand facet. Don't pass `simple_debug=false`; it causes HTTP 500 errors.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/product_opportunities.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the account and site

1. Call `list_discovery_accounts`. If the list is long, filter it for the account the user named, and ask if it's still ambiguous.
2. Call `list_discovery_sites`. If there's more than one site, ask which to use, and pass its `domain_key` and `view_id` to the reporting tools.
3. If the account has **no sites**, report at account level: leave out `site_group_id`, `domain_key` and `view_id`, and use the account name as the product grid's `domain_key`. Tell the user.

### 2. Get the totals and every product

1. Call `get_discovery_products_overview` with `days` (default 30). Note revenue, visits, conversion rate and the `trends`. The account's own trend matters: in a fast-growing period, a product that is flat is losing ground.
2. Call `get_discovery_product_performance_table` with `sort="revenue"` and a `page_size` that covers `total_rows` (call once with `page_size=1` to read `total_rows`; one page of 7,000 worked in testing). Every row has the current and `prev_*` value of visits, product page views, add-to-cart (ATC), conversions, revenue, RPV, AOV, ATC rate and conversion rate. **There are no impressions**: "visibility" here means product page visits.
3. **Catalog size, for dead weight.** Call `search_discovery_product_grid_insights` with `query="*"`, `rows=1`, `fl="pid"` and `extra_params={"facet":"false"}`, and read `data.response.numFound`. If it is larger than the table's `total_rows`, the difference is products nobody viewed. To list them, page through the same call with `rows=200` and `start` (one call at a time), and pass the saved pages to the script with `--catalog-pids` (one file of product IDs, one per line, also works).

### 3. Sort the products

Run [scripts/product_opportunities.py](scripts/product_opportunities.py) on the saved table:

```
python3 <this skill's folder>/scripts/product_opportunities.py products.json --markdown
python3 <this skill's folder>/scripts/product_opportunities.py products.json --catalog-pids catalog_pids.txt --out groups.json
```

It works out the typical (median) product's ATC rate, conversion rate and RPV, then places each product with at least 30 visits in one group, the one with the most revenue at stake:

- **High visibility** is the top 10% of products by visits; **low visibility** is the bottom half.
- **Well below or above typical** means at least 15% from the median **and** the product's 90% confidence interval excludes the median, so a product with 40 visits and a lucky week isn't flagged.
- **Declining winners** are the top 10% by previous-period revenue whose revenue is at least 20% behind where the account's trend would have put it. For each, the script says whether the **driver** was visibility (visits fell behind the account), conversion, or order value.

Change the thresholds with the options listed in the script (`--high-pct`, `--gap`, `--decline` and so on) if the account is small or the user wants a longer or shorter list. If you can't run scripts, follow the rules in [references/opportunity-playbook.md](references/opportunity-playbook.md) by hand.

Read the groups with judgement:

- If the account grew or shrank a lot (the overview `trends`), say so. Declining winners are measured against that trend, so a product can grow in dollars and still be "declining".
- If a group is empty, say so plainly. That is a finding, not a failure.
- A product's views can come from search, category pages or recommendations. The table doesn't say which.

### 4. Check where the key products rank

For the top 3–5 **hidden gems**, **declining winners driven by visibility**, and **over-exposed** products:

1. **Find the product's main query.** Take the product type from the title ("ring", "jeans", "suit"), and call `get_discovery_query_performance` with `search=<product type>` and `sort="browse_sessions"`. Pick the highest-traffic query that fits the product. Reuse queries across products of the same type.
2. **Run the product grid** for that query with `rows=200`, `fl="pid,title,brand,price"`, one call at a time. Save it.
3. Run [scripts/grid_positions.py](scripts/grid_positions.py):

   ```
   python3 <this skill's folder>/scripts/grid_positions.py grid.json --pids 110467,107119 --brand "Brand name"
   ```

   It gives each product's position, the brand mix of the first 24, any ranking rules applied, and whether an A/B test is running.

Interpret the position:

| Group | Position | Meaning |
|---|---|---|
| Hidden gem | below 24 (off the first page) | **Boost candidate**: a converting product shoppers rarely reach |
| Hidden gem | in the first 24 | Its low visibility comes from elsewhere (few searches, or category pages). Check its category instead |
| Declining winner (visibility) | just below 24, or in a crowded first page dominated by one brand | Likely pushed down. Diagnose the query, or test a boost |
| Over-exposed | in the first 12 | **Bury candidate** on this query |
| Over-exposed | deep in the results | Its views come from somewhere else (a category, recommendations, a campaign). Don't bury it in search; find the source |

To check a category instead of a query, run the grid with `search_by="category"` and the category ID.

### 5. Recommend actions

Read [references/opportunity-playbook.md](references/opportunity-playbook.md) for the action, the revenue maths and the hand-off for each group. For every product you list, give:

- **the action**: specific, for example "Boost 'Goldmaster de Pacific Style ring' on 'ring', where it sits at position 74";
- **the evidence**: its metrics against the typical product, and its position;
- **the revenue at stake, with the working** from the script, for example "(100 − 46) visits × 28.4% CR × $398 AOV = $6.1k". Present it as an upper bound for the period, not a forecast;
- **the hand-off**: `discovery-experiment-setup` for a boost or bury test, `discovery-query-diagnosis` when a declining winner's main query itself looks broken, or "product page / pricing team" when it isn't a search fix.

Rank the actions by revenue at stake. Group products of the same brand or type where the same action covers them (for example "four Peter England and Parx suits").

## Output

```
## Product opportunities: <account/site>, last <N> days

**Headline:** <one sentence: the biggest opportunity and how much is at stake>

<products in report> products; typical product: ATC <x>%, conversion <y>%, RPV $<z>.
Account trend: revenue <+/-n>% on the previous period.

### Fix the product page (<count>, up to $<total>)
| Product | Brand | Visits | ATC (typical) | Conversion | At stake (working) | Action | Hand-off |

### Hidden gems (<count>, up to $<total>)
| Product | Brand | Visits | Conversion (typical) | Main query: position | At stake (working) | Action | Hand-off |

### Declining winners (<count>, up to $<total>)
| Product | Revenue now (prev) | vs account trend | Driver | Main query: position | At stake (working) | Action | Hand-off |

### Over-exposed (<count>, up to $<total>)
| Product | Visits | Conversion (typical) | Where it ranks | At stake (working) | Action | Hand-off |

### Dead weight (<count>)
<products with no views; what to do with them>

### Next steps
1. <the highest-value action, and the skill to run>
2. ...

**Caveats:** <thresholds used, small samples, account-level reporting, demo or partial data>
```

Show the top 5–10 per group. Offer the full list as a file if the user wants it.

## Safety

This skill is **read-only**. It never boosts, buries, creates rules or changes products.

If the user asks to act on a recommendation, hand off to `discovery-experiment-setup` for a boost or bury test. That skill confirms every write. Never use a write tool from this skill.

- **Never repeat** `auth_key` URLs from grid debug output (`feUrl`, `sqApiUrl`), editor emails (`lastModifiedBy` in synonyms), or internal commercial fields such as `margin` or `cost`.
