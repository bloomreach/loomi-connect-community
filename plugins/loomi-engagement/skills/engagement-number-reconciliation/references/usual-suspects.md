# Usual suspects: why two numbers differ

The causes found most often when two Engagement numbers disagree, each with the symptom, the check and the EQL to run. Work through the ones that fit the definition grid's "different" and "unknown" rows, cheapest first.

Replace event, property and consent names with the project's own (`get_event_schema`, `get_customer_property_schema`, `get_consent_settings`). `<C0>`/`<C1>` are the period's start and end as ISO dates ending in `Z`; `until` is exclusive. `<prop>` is any low-cardinality customer property (never email, phone, name or an ID): a `select` needs a `by`, so break down by it `with null` and **add up every row**. Escape backslashes and double quotes in any name or value you put inside quotes.

**Ran** = executed in read-only testing on a sandbox project (about 75,000 customers), November 2026. Example figures are from that test, rounded.

## Quick checks (no EQL)

| Symptom | Check | Reading |
|---|---|---|
| A customer count looks too big | Compare it with `total_customers` from `get_project_overview` | **Equal = a filter was dropped.** The number is the whole base, whatever the label says |
| A count over a long window looks too small, or "everyone is new" | `oldest_timestamp` from `get_project_overview`, and the oldest date in the other source | History in one source starts later than the window. Anything "first", "ever", "lifetime" or "since" is cut off there |
| A saved report looks windowed but the number is huge | The report's `date` filter: `enabled: false` with a `duration` | The window is configured but switched off, so it covers all time |
| A segment reads 0, or a catch-all segment reads the whole base | The segmentation's `segments[]` in order | Segments are first-match-wins: see S below |

## 1. Consent category vs a "subscribe" property (Ran, medium)

Symptom: "subscribed", "opted in", "can email" counts disagree by a lot. One side uses the consent category (`has consent <category>`), the other a customer property such as `email_subscribe = "subscribed"`. They are different things: the property is often an imported flag that nobody keeps in step with consent.

```
select count customers, count customers matching (has consent <category>) by customer.<subscribe_property> grouping top 5 with null customers matching <the shared audience condition>
```

- Rows are the property's values (`subscribed`, `unsubscribed`, `null`); the two columns are all customers and those with valid consent. The cross-tab explains the whole gap: consent holders whose property says `unsubscribed` or is empty, minus property-subscribed customers without consent.
- In testing, for one month's buyers (rounded to 10): 12,650 with valid consent vs 6,130 with the property; 2,070 "unsubscribed" and 4,900 with no value still held valid consent, and 450 "subscribed" had none (6,130 − 450 + 2,070 + 4,900 = 12,650).
- Which is right: for "who may we email", consent. Get the category ID from `get_consent_settings` (via `search_tools` / `call_tool` if it isn't listed).

## 2. Dropped filter (Ran, medium)

Symptom: the number equals the project's total customers, or a "UK customers with SMS consent" count equals everyone.

```
select count customers, count customers matching (has consent <category>) by customer.country grouping top 10 with null
```

- Rows add up to the whole base, so you see both the base and the filtered count. In testing: base 75,000; one country 57,000; that country with SMS consent 21,900. The disputed number was the base.
- A `null` row shows how many customers have no value for the filter field (see 6).

## 3. History that starts later than the window (Ran, medium)

Symptom: "new" or "first-time" counts far too high in one source; lifetime or 365-day counts far too low. Typical when a warehouse, BI tool or export holds only recent months while Engagement has years.

```
select count customers matching (exists[event purchase since <C0> until <C1>] and not exists[event purchase until <C0>]), count customers matching (exists[event purchase since <C0> until <C1>] and not exists[event purchase since <other_source_start> until <C0>]), count customers matching (exists[event purchase since <C0> until <C1>]) by customer.<prop> grouping top 3 with null
```

- Column 1: first purchase ever. Column 2: "first" if history began at `<other_source_start>`. Column 3: everyone who bought in the period.
- In testing, for one month: 36 first-ever buyers; 8,260 "first-time" if history started four days before the month (which reproduced the other source's number exactly); 8,430 buyers in total.

## 4. Data that stops early, lags, or isn't loaded yet

Symptom: the latest period is much lower in one source; "today" or "yesterday" differs; the gap shrinks when you rerun later.

```
select count event <event> by event <event> timestamp grouping top 62 format year month day since <C0> until <C1>
```

- One row per day with data. Missing days are gaps; the last row is the data horizon. Comparing a period that runs past the horizon reads as a fall that isn't there.
- Exports and warehouses load on a schedule (often once a day), so the latest hours or days are missing there but live in Engagement. Ask for the other source's refresh time.

## 5. Time zone (Ran, high)

Symptom: daily or monthly figures differ slightly, most at the edges; totals over long windows agree.

- `since … until …Z` is UTC. Day and month buckets (`format year month day`) follow the **project's** time zone, including daylight saving: the bucket's header is the Unix time of local midnight, which shows the offset (`…T00:00:00Z` = UTC, `…T22:00:00Z` = UTC+2).
- Rebuild the other side's day in its own zone: 1 July in Central European Summer Time is `since 2026-06-30T22:00:00Z until 2026-07-01T22:00:00Z`.
- In testing: 267 orders on 1 July in UTC, 264 in UTC+2.

## 6. Empty filter fields (fill rate) (Ran, medium)

Symptom: a filtered count is much smaller than expected, and the person calls it "all UK customers".

```
select count customers, count customers matching customer.<filter_property> has value by customer.<prop> grouping top 3 with null
```

- Add up each column. All customers minus those with a value is everyone the filter silently drops.
- Count `has value`; never break down by the field itself if it could hold personal data (email, phone, name, an ID). Only for a low-cardinality field such as country, `by customer.<filter_property> grouping top 10 with null` also shows mixed formats (`GB`, `UK`, `United Kingdom`), which split one value into several.
- For event properties: `select count event <event>, count event <event> where .<property> has value by event <event>.<low_cardinality_property> grouping top 3 with null since <C0> until <C1>`.

## 7. Events counted as orders: statuses and repeated order IDs (Ran, high)

Symptom: orders or revenue too high in one source, often by a steady factor (×2 to ×3).

```
select count event purchase, sum event purchase.<value> by event purchase.<status> grouping top 10 with null since <C0> until <C1>
select count event purchase, sum event purchase.<value> by event purchase.<order_id> grouping top 3 since <C0> until <C1>
```

- First query: every status value. If an order logs one event per status (`pending`, `paid`, `shipped`, `refunded`), counting all events counts each order several times and sums its value several times. Count the completed status only.
- Second query: the three order IDs with the most events. Each should have 1. In testing, a two-month window was clean, but a three-year window had two IDs with over 1,100 events each (about $720,000 of "revenue"). Rows are sorted by ID, not by count. **Report counts only** (how many IDs repeat, how many events and how much value they carry), never the order IDs themselves.
- EQL has no distinct count of a property (`count distinct` doesn't parse).

## 8. Sends: enqueued, sent, delivered (Ran, high)

Symptom: "emails sent" differs between a report, an AI answer and the ESP.

```
select count event campaign where .campaign_name = "<name>", count first event campaign where .campaign_name = "<name>" by event campaign.status grouping top 15 with null since <C0> until <C1>
```

- Rows are statuses; columns are events and unique customers. Email records `enqueued`, `delivered`, `opened`, `clicked`, `hard_bounced`, `soft_bounced`, `unsubscribed` and `complained`, with **no `sent`** (some projects spell bounces `hard_bounce` / `soft_bounce`). SMS and push record `sent` and no `delivered`. So "emails sent" can mean `enqueued` or `delivered`; for SMS and push it means `sent`.
- In testing, one newsletter: 41,000 enqueued and 39,700 delivered.
- `<name>` is the campaign name as the project spells it: escape backslashes and double quotes before putting it in the query.
- The ESP usually counts what it accepted or delivered; Engagement's `enqueued` includes messages later dropped.

## 9. Per send vs per unique customer (same query as 8)

Symptom: open or click rates differ two- or threefold.

- Per send: opened events ÷ delivered events. Unique: customers who opened ÷ customers delivered to. Mixed: unique openers ÷ delivered events.
- In testing, the same newsletter gave 69% (opened events ÷ delivered events), 88% (unique openers ÷ unique recipients) and 47% (unique openers ÷ delivered events), because most customers got two sends and some opened several times. Clicks: 3.9% per send vs 7.1% per customer.
- Also check the denominator: delivered vs sent vs enqueued.

## 10. First-ever buyers vs anyone who bought (Ran, medium)

Symptom: "new customers" counts differ by orders of magnitude. One side means "first purchase ever falls in the period", the other "bought in the period" or "first purchase in our data".

Same query as 3, columns 1 and 3. In testing: 36 vs 8,430 for one month.

## S. Segmentations: first match wins (Ran, medium)

Symptom: a later segment reads 0 or too few; a "rest" or "other" segment reads the whole base; segment sizes from another tool don't match the UI.

- In a segmentation, each customer belongs to the **first** segment whose filter matches. A segment with the same or a narrower filter than an earlier one is always empty. A last segment with an empty filter is "everyone else", but evaluated on its own (by another tool, or by rebuilding just its filter) it matches the whole base.
- Rebuild each segment as "its filter, and none of the earlier ones":

```
select count customers matching (<filter 1>), count customers matching (<filter 2> and not (<filter 1>)), count customers matching (not (<filter 1>) and not (<filter 2>)) by customer.<prop> grouping top 3 with null
```

- In testing, a "2+ / 1 / rest" purchase segmentation rebuilt as 73,800 / 1,220 / 40, matching the saved report; the catch-all evaluated alone gave 75,000. (That run wrote the conditions without brackets, `not count event purchase >= 2`; the bracketed form above parsed too.)
- Also check the segmentation's global `customer_filter`: it applies to every segment.

## Other causes to rule out

| Cause | Check |
|---|---|
| Different event: order-level vs item-level purchase, or a view event vs a session | The event name in each definition; item-level counts line items |
| Different value: with or without tax, shipping or refunds; list price vs paid price | The value property in each definition |
| Mixed currencies added up | Break the sum down by the currency property |
| Window bounds: rolling vs calendar, inclusive vs exclusive end, no end at all | Write both windows as `since … until …Z`; an open end also counts future-dated events |
| Unique customers added up across rows | A customer can appear in several rows of an event breakdown; only events and sums add up |
| Breakdown dropped rows | Multi-dimension breakdowns drop rows with a `null` in any dimension unless `with null`; customer-ID breakdowns drop customers with no ID |
| Identity | Profiles vs people: anonymous and merged profiles, cookies vs registered IDs. Exports keyed by email miss customers with no email |
| Report cache | `calculate_report` returns Engagement's cached result; an old cache can lag a live EQL rebuild |
| Snapshot vs live | A number saved in a document, dashboard text or earlier AI answer is a snapshot. Rerun it before comparing |
