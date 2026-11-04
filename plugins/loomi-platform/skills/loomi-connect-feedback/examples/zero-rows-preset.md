# Example: a known (bug?) item, sent as one report

Illustrative only. The account, IDs and response are made up, and the line number will differ in your copy of the file.

**Prompt:** "Which of the known Loomi Connect bugs haven't we reported? I'll pick one."

## The list (from `list-known`)

| # | Line | Section | Tools | Item |
|---|---|---|---|---|
| 1 | 74 | Discovery / Product grid | `search_discovery_product_grid_insights` | `simple_debug=false` returns HTTP 500 |
| 2 | 128 | Discovery / Query, product and brand performance | `get_discovery_category_performance_table` | `filter_preset="lowest_converting"` returns 0 rows |
| 3 | 209 | Discovery / Catalog and pixel | `search_discovery_catalog_jobs` | ignores `status="failure"` |
| … | | | | |

> Pick one and I'll write it up and show you the full report before anything is sent. Each report is confirmed on its own.

The user picked 2 and said the account's brand name must not appear.

## The confirmation

The private terms file listed the account's site and brand names. The plan was `ready` with two warnings, and the confirmation showed `payload_preview` verbatim:

`````
Will send ONE feedback report to the Loomi Connect team (nothing in Bloomreach changes; it can't be withdrawn).
Exactly what will be sent:

gap_type: INCOMPLETE_DATA
completion_estimate: 3
client: (never sent; the tool detects it)
model: (never sent; the tool detects it)
----- feedback -----
[Loomi Connect Community report] get_discovery_category_performance_table: filter_preset=lowest_converting returns 0 rows

Product: discovery | Environment: production

Expected: The lowest-converting categories with enough traffic, as the description says.
Actual: success: true with total_rows 0, while the same call without filter_preset returns rows.

Minimal reproduction (IDs, names, emails, URLs and secrets replaced with placeholders):
  tool: get_discovery_category_performance_table
  arguments: {"account_id": "<accountid>", "days": 30, "filter_preset": "lowest_converting"}

Response excerpt (placeholders as above):
{"data": {"rows": [], "total_rows": 0}, "success": true}

Recorded in the Loomi Connect Community repo's known tool behaviour (Discovery / Query, product and brand performance, line 128): https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L128
> - `get_discovery_category_performance_table` with `filter_preset="lowest_converting"` returns 0 rows. **(bug?)**

Suggestion: Apply the preset, or say in the description which accounts it works for.
----- what_i_tried -----
Called it with days 7 and 30, with and without filter_preset; sorted the unfiltered table by conversion instead.

Known item:  https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L128    Environment: production
Warnings (each with field, line and the match masked except its first letter):
  - redacted: placeholders were put into arguments and response_excerpt (account_id became <accountid>)
  - person (soft): what_i_tried line 1 has a word after 'by' that may be a name (c... (18 characters)): "by conversion", not a name
Read every line above; redaction is best effort.
Send this report? (yes / no)
`````

The user said yes.

## After sending

```
## Loomi Connect feedback: get_discovery_category_performance_table

**Sent:** accepted (ID fb-0001)
**Summary:** filter_preset=lowest_converting returns 0 rows · **Gap type:** INCOMPLETE_DATA · **Environment:** production
**Known item:** https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L128
**Read-back:** none; Loomi Connect has no tool to read a sent report, so this is the tool's response only.

**Next:** when the team confirms a fix, update docs/known-tool-behaviour.md by pull request (remove the (bug?) mark or the item).
```

The user then asked to send item 3 as well. That was a new report: built, shown in full and sent only after its own yes.
