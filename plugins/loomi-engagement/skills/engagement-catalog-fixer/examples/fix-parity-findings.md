# Example: fixing catalog parity findings

**This example is illustrative.** The project, catalog, items and values are made up; the shape follows the script's output on synthetic fixtures.

**Prompt:** "Fix the stock and price problems the catalog parity check found. Also remove OLD1, it's discontinued."

## Plan (Example Store / products, v1 catalog)

Read 6 items with `get_catalog_item`. P500 isn't in the catalog, so it can't be fixed here (an upsert would create a half-empty item). P600 is missing from Engagement altogether: the import needs to include it.

**Batch 1: update 4 items**

| # | Item | Field | Before | After | Why |
|---|---|---|---|---|---|
| 1 | P100 Trail Runner Shoe | availability | In Stock | Out Of Stock | out of stock on the site |
| 1 | | sale_price | 120 | 99 | site's sale price |
| 2 | P200 Rain Jacket | stock_level | 12 | 0 | out of stock on the site |
| 3 | P300 Wool Socks | price | "18.50" | 15 | site's price |
| 4 | P400 | url | (none) | https://shop.example/p/p400 | site's URL |

Skipped: P100's title (the parity output cuts long text off, so the full title is needed to fix it). Warning: P400 holds 1 of the 9 fields the catalog defines, so an earlier partial write probably wiped it; the update keeps what's there, and the full record has to come from the feed.

> Update these 4 items in products (Example Store)? Recommendations and emails use the new values within minutes, and the next catalog import will overwrite them unless the feed is fixed too. (yes / no)

**Batch 2: delete 1 item**

> Delete item OLD1 ('Discontinued Stove') from products? It's permanent; the plan saves the full item so it can be recreated. Mark it out of stock instead? (delete / out of stock / skip)

## Report

| # | Item | Change | Result |
|---|---|---|---|
| 1 | P100 Trail Runner Shoe | availability In Stock → Out Of Stock; sale_price 120 → 99 | in_place |
| 2 | P200 Rain Jacket | stock_level 12 → 0 | in_place |
| 3 | P300 Wool Socks | price 18.50 → 15 | in_place |
| 4 | P400 | url added | in_place |
| 5 | OLD1 Discontinued Stove | deleted | gone |

**Not changed:** P500 (not in the catalog), P600 (missing from Engagement: fix the import), P100's title (needs the full value).
**Undo plan:** work/plan.json
**Next:** the Engagement import runs weekly and the site feed hourly, so these fixes will be overwritten on the next import: move stock and price to a daily import (`data-feed-health`), then run `catalog-parity-check` again.
