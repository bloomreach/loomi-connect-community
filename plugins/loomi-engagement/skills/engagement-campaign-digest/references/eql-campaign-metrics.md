# EQL patterns for campaign metrics

Bloomreach Engagement records every campaign message outcome as a `campaign` event. Useful properties:

| Property | Meaning |
|---|---|
| `status` | What happened, e.g. `enqueued`, `sent`, `delivered`, `opened`, `clicked`, `hard_bounced`, `soft_bounced`, `unsubscribed`, `complained`, `failed`. Some projects spell them `hard_bounce`, `soft_bounce` and `unsubscribe`; the script treats both spellings as one. Email usually has `delivered` and no `sent`; SMS and push usually have `sent` and no `delivered`. Values vary by channel and project: run pattern A first to see which ones exist. |
| `action_type` | Channel: `email`, `sms`, `mms`, `webhook`, `mobile notification`, `browser notification` (with spaces) and others. |
| `campaign_name`, `campaign_id` | The campaign or scenario. |
| `action_name`, `action_id` | The send step inside a scenario. One scenario can have several. |
| `variant` | A/B variant name. |
| `consent_category`, `campaign_policy` | Consent category and frequency policy used. |
| `message`, `status_code` | Error detail for failures and bounces. |

## Syntax that was checked

These forms were parsed by `estimate_eql_cost` and, for pattern A, executed:

- Relative range: `in last 7 days`, at the end of the query.
- Absolute range: `since 2026-09-21T00:00:00Z until 2026-09-28T00:00:00Z`. Always add `Z`. `from ... to ...` is a parse error.
- Event filter: `where .action_type = "email"`, using the `.property` shorthand. Only `and` is allowed between conditions.
- Breakdown: `by event campaign.status grouping top 15`. Always add `grouping top N`.
- Cross-tab: `by row <attr> grouping top N by column <attr> grouping top N`.

A query with no date range scores `very_high`. Always bound it.

## Patterns

**A. Status mix for one channel and period** (cost: `high` on large projects; run it)

```
select count event campaign where .action_type = "email" by event campaign.status grouping top 15 since <start>Z until <end>Z
```

The response has `data.rows[]`, each with `headers[0].value` (the status) and `values[0]` (the count). An empty `rows` list means no campaign events in that period.

**B. Status by campaign (cross-tab)** (cost: often `very_high`; estimate first)

```
select count event campaign where .action_type = "email" by row event campaign.campaign_name grouping top 20 by column event campaign.status grouping top 12 since <start>Z until <end>Z
```

**C. One status by campaign** (use instead of B when B is `very_high`; one query per status)

```
select count event campaign where .action_type = "email" and .status = "delivered" by event campaign.campaign_name grouping top 25 since <start>Z until <end>Z
```

Run it for `delivered`, `clicked` and, if they appeared in pattern A, the bounce and unsubscribe statuses, spelled as pattern A returned them. Skip `opened` if you're short on budget: opens are inflated by mail privacy features and are the least reliable signal.

**D. Revenue by campaign (only if the purchase event has a campaign or UTM property)**

Check `get_event_schema` for a property such as `utm_campaign` on the purchase event. The property and event names below are examples; use the project's own.

```
select sum event purchase.total_price by event purchase.utm_campaign grouping top 20 since <start>Z until <end>Z
```

Label it "purchases tagged with the campaign's UTM", not "attributed revenue".

## Rate definitions

Use whichever send count exists: `sent` if present, otherwise `enqueued`, otherwise `delivered + bounces + failed`.

| Rate | Formula |
|---|---|
| Delivery rate | delivered ÷ sends |
| Bounce rate | (hard_bounced + soft_bounced) ÷ sends |
| Open rate | opened ÷ delivered (event-based) |
| Click rate | clicked ÷ delivered (event-based) |
| Click-to-open | clicked ÷ opened |
| Unsubscribe rate | unsubscribed ÷ delivered |
| Complaint rate | complained ÷ delivered |
| Failure rate | failed ÷ sends |

Counts are events, not unique customers, so a customer who opens three times counts three times. Say so in the output.

## Budgeting queries

A typical weekly digest needs:

- 2 queries per channel for pattern A (this period and the previous one);
- 1 cross-tab (B), or 3–5 single-status queries (C), for this period.

That is about 4–9 queries. Space them at least 3 seconds apart. If the user wants per-campaign comparisons with the previous period too, double the per-campaign count, and tell them first.
