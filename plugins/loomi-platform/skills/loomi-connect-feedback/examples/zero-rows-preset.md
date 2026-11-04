# Example: a known (bug?) item, sent as one report

Illustrative only. The account, IDs and response are made up, and the line number will differ in your copy of the file.

**Prompt:** "Which of the known Loomi Connect bugs haven't we reported? I'll pick one."

## The list (from `list-known`)

| # | Line | Section | Tools | Item |
|---|---|---|---|---|
| 1 | 73 | Discovery / Product grid | `search_discovery_product_grid_insights` | `simple_debug=false` returns HTTP 500 |
| 2 | 127 | Discovery / Query, product and brand performance | `get_discovery_category_performance_table` | `filter_preset="lowest_converting"` returns 0 rows |
| 3 | 202 | Discovery / Catalog and pixel | `search_discovery_catalog_jobs` | ignores `status="failure"` |
| … | | | | |

> Pick one and I'll write it up and show you the full report before anything is sent. Each report is confirmed on its own.

The user picked 2 and said the account's brand name must not appear.

## The confirmation

````
[Loomi Connect Community report] get_discovery_category_performance_table: filter_preset=lowest_converting returns 0 rows

Product: discovery | Environment: production

Expected: The lowest-converting categories with enough traffic, as the description says.
Actual: success: true with total_rows 0, while the same call without filter_preset returns rows.

Minimal reproduction (IDs, account and project names, emails, URLs and secrets replaced by placeholders):
  tool: get_discovery_category_performance_table
  arguments: {"account_id": "<accountid>", "days": 30, "filter_preset": "lowest_converting"}

Response excerpt (placeholders as above):
{"success": true, "data": {"total_rows": 0, "rows": []}}

Recorded in the Loomi Connect Community repo's known tool behaviour (Discovery / Query, product and brand performance, line 127): https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L127
> - `get_discovery_category_performance_table` with `filter_preset="lowest_converting"` returns 0 rows. **(bug?)**

Suggestion: Apply the preset, or say in the description which accounts it works for.
````

```
Will send ONE feedback report to the Loomi Connect team (nothing in Bloomreach changes; it can't be withdrawn):
  Tool:        get_discovery_category_performance_table
  Summary:     filter_preset=lowest_converting returns 0 rows
  Gap type:    INCOMPLETE_DATA    Completion estimate: 3 of 5
  Environment: production
  Known item:  https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L127
  Feedback:    1012 characters   What I tried: 118 characters
  Warnings:    none
Send this report? (yes / no)
```

The user said yes.

## After sending

```
## Loomi Connect feedback: get_discovery_category_performance_table

**Sent:** accepted (ID fb-0001)
**Summary:** filter_preset=lowest_converting returns 0 rows · **Gap type:** INCOMPLETE_DATA · **Environment:** production
**Known item:** https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L127
**Read-back:** none; Loomi Connect has no tool to read a sent report, so this is the tool's response only.

**Next:** when the team confirms a fix, update docs/known-tool-behaviour.md by pull request (remove the (bug?) mark or the item).
```

The user then asked to send item 3 as well. That was a new report: built, shown in full and sent only after its own yes.
