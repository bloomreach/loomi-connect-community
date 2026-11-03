# Opportunity pattern library

Each pattern is an **aggregate** customer count. None of them lists or reads individual customers.

Status labels:
- **Ran:** executed with `execute_analytics_eql` in live, read-only testing (October 2026) against a sandbox project (as-of dates moved with `execution_time`, because it has no recent purchases) and, for some, a production project.
- **Parsed:** accepted by `estimate_eql_cost`, not executed.

Replace the event and property names with the project's own, from `get_event_schema` and `get_customer_property_schema`. The names below are the common Bloomreach defaults (`purchase`, `purchase_item`, `view_item`, `cart_update`, `campaign`, `session_start`, `total_price`, `category_level_1`, `voucher_value`).

## The count wrapper (Ran)

Every pattern goes inside the same wrapper, reused from `engagement-segment-builder`:

```
select count customers by customer.<low_cardinality_property> grouping top 3 with null customers matching <conditions>
```

- **Add up every row**, including `null`, `""` and `{"type": "other"}`. In testing, the `null` row alone often held most of the total.
- **Zero comes back as an empty `rows` list.** Treat it as 0, not as an error.
- On large projects every one of these is rated `high`, whatever the window. That's normal for customer scans. Ask once before the run, not per query.
- EQL allows about **one query every 3 seconds for the whole Engagement instance** (estimates count too). Wait 4 seconds between calls. Expect at least one 429 in a full run; wait 6–10 seconds and retry.

## Syntax that matters here (all Ran)

- **Windows go inside `exists[...]`**, after `where`: `exists[event view_item where .category_level_1 = "x" in last 30 days]`.
- **Counting events with a filter and a window** works as one expression: `count event view_item where .category_level_1 = "x" in last 30 days >= 3`. The window really applies: in testing, the same condition without `in last 30 days` matched several times as many customers.
- `count event purchase where .voucher_value > 0 >= 1` works and matched exactly the `exists[...]` form.
- `has value` works inside `where`: `exists[event purchase_item where .category_level_1 has value]`.
- `is in [...]` works inside `where`: `.action_type is in ["email", "sms", "mobile notification", "browser notification"]`.
- `has consent <category_id>` and `not has consent <category_id>` work in `customers matching`.
- **`execution_time` caps every event, not just windows.** An unwindowed `count event purchase >= 1` with `execution_time` before the first purchase returned 1 instead of the lifetime total. So "lifetime" conditions in an as-of test mean "lifetime up to that date". That's what you want for a back-test.
- `customer.email_address has value` works as a reachability check.

## Before the patterns: three checks

### C1. Find the as-of date (sandbox only)

If `exists[event purchase in last 90 days]` is empty, find a period with data using absolute windows (`since 2024-01-01T00:00:00Z until 2025-01-01T00:00:00Z`), halving the range each time, then set `execution_time` to a date inside it. Say "as of <date>" in the output. **(Ran)**

### C2. Match the category taxonomy (view side vs purchase side)

Category values on `view_item` and on `purchase_item` can be in **different formats**. In testing, `view_item.category_level_1` held slugs (`womens-…`) while `purchase_item` held display names, so `not exists[event purchase_item where .category_level_1 = "<slug>"]` matched everyone and the "never bought it" half did nothing.

1. Get the top viewed categories (Ran, rated `high`, 30-day window):
   ```
   select count event view_item by event view_item.category_level_1 grouping top 5 with null in last 30 days
   ```
2. For each category you'll use, check that the purchase side matches at least some buyers (Ran):
   ```
   ... customers matching exists[event purchase_item where .category_level_1 = "<value>"]
   ```
3. If that's empty but `exists[event purchase_item where .category_level_1 has value]` isn't, the formats differ. Use `contains` on a shared stem against `categories_path` (Ran: `.categories_path contains "<stem>"`), and say so.

Don't break down `purchase_item` by category over 90+ days: it rated `very_high`.

### C3. Measure reachability once

Reachability decides the ranking, so measure it, don't assume it:

- **Contactable:** `customer.<email property> has value` (Ran). In a production test, nearly all recent one-time buyers had an email address, but only a small fraction of recent cart abandoners did: most browsers are anonymous.
- **Consent:** `has consent <id>` (Ran). **First check that consent is used at all:** `... customers matching has consent <id>` for the whole project. In a production test this was **empty for every customer**: consent wasn't recorded in Engagement. Then report "consent isn't tracked in Engagement, so reachability is based on contact data only", not "nobody has consent".
- **On-site:** anyone with a recent `session_start` can be reached with a web layer, even anonymously.

## The patterns

### P1. Browsed a category but never bought it (Ran)

Plain English: viewed products in category X in the last 30 days and hasn't bought anything in X in the last year.

```
customers matching exists[event view_item where .category_level_1 = "<X>" in last 30 days]
  and not exists[event purchase_item where .category_level_1 = "<X>" in last 365 days]
```

- Use the item-level purchase event for the category (`purchase_item`); `purchase` has no category.
- Run C2 first. Then the variant using `contains` on the purchase side **(Ran)**.
- Strengthen intent with a view count: `count event view_item where .category_level_1 = "<X>" in last 30 days >= 3` **(Ran)**.
- Run for the top 2–3 viewed categories only.
- Reachability is usually low (browsers are often anonymous): count `and customer.<email property> has value` as well.

### P2. One-time buyers in their likely repeat window (Ran, sandbox and production)

Plain English: bought exactly once, and that purchase was 31–90 days ago.

```
customers matching count event purchase = 1
  and exists[event purchase in last 90 days] and not exists[event purchase in last 30 days]
```

- Adjust the window to the business: consumables 21–45 days, apparel 30–90, parts and durables 60–180. Ask the user, or state the default.
- Doesn't overlap `winback-opportunity`, which starts at 31 days but covers all frequencies and goes to 365+. Say so if both skills are used: this is the **one-order** slice of its 31–90 band.

### P3. High-value customers who are slowing down (Ran)

Plain English: repeat customers with lifetime spend over a threshold, who bought in the last year but not in the last 60 days.

```
customers matching count event purchase >= 2 and sum event purchase.total_price >= <threshold>
  and exists[event purchase in last 365 days] and not exists[event purchase in last 60 days]
```

- Threshold: about 3 × AOV, or the user's VIP definition. Reuse an existing VIP or value segmentation if one exists.
- "Still browsing" variant: add `and exists[event session_start in last 30 days]` **(Ran)**. In testing this emptied the audience because purchases weren't linked to the browsing identity. If it's empty, report the base group and say why.
- Stop at 365 days. Customers beyond that belong to `winback-opportunity`; hand them off rather than sizing them here.

### P4. Customers who mostly buy on discount (Ran)

Only if the purchase event has a discount property (`voucher_value`, `voucher_code`, `discount_value` on `purchase_item`, or `original_price` vs `price`). Otherwise skip it and say so.

```
customers matching count event purchase where .voucher_value > 0 >= 2 and count event purchase <= 3
```

- "Mostly" can't be written as a ratio in EQL. This approximates it as "at least 2 discounted orders out of at most 3". Also count `count event purchase where .voucher_value > 0 >= 1` **(Ran)** to show how common discounts are.
- Item-level variant: `count event purchase_item where .discount_value > 0 in last 365 days >= 2 and exists[event purchase in last 365 days]` **(Ran)**.
- The value here is **margin protected**, not new revenue: route them to non-price offers (early access, bundles, loyalty points) and keep discounts away from full-price buyers.

### P5. Category affinity × what's trending in search (Ran on the Engagement side; the join is manual)

Plain English: customers who keep looking at a category that shoppers are searching for more this week.

1. Get rising searches from Discovery: `get_discovery_query_performance` with `days=7`, `sort="browse_sessions"`, `page_size=100`, and rank them as `discovery-trending-searches` does (traffic-adjusted, not raw `change_*`). Keep the top 3 rising queries with healthy conversion.
2. Map each query to an Engagement category value by hand (for example "shorts" → the shorts category). Say how you mapped it.
3. Count the affinity audience:
   - **If** a category-affinity customer property exists and is filled (check its fill with `by customer.<affinity property> grouping top 5 with null`, **Ran**): `customer.<affinity property> = "<category>"`.
   - **Otherwise** (in testing the property existed but was empty for almost all active viewers): behavioural affinity, `count event view_item where .category_level_1 = "<category>" in last 30 days >= 3` **(Ran)**.
4. Optionally exclude people who bought it recently: `and not exists[event purchase_item where .category_level_1 = "<category>" in last 30 days]`.

Discovery has no customer IDs, so this is a **join by category name**, not by person. Say so.

### P6. Cart abandoners who weren't contacted (Ran, sandbox and production)

Plain English: added to cart in the last 7 days, didn't buy, and got no email, SMS or push in that time.

```
customers matching exists[event cart_update where .action = "add" in last 7 days]
  and not exists[event purchase in last 7 days]
  and not exists[event campaign where .action_type is in ["email", "sms", "mobile notification", "browser notification"] in last 7 days]
```

- **Filter the `campaign` event by message type.** In a production test, almost all `campaign` events in a week were A/B split assignments (`action_type = "split"`), so `not exists[event campaign ...]` without a type filter would call almost everyone "contacted". Check the values first (Ran, rated `high`, 7-day window): `select count event campaign by event campaign.action_type grouping top 5 with null in last 7 days`.
- If the project has no `campaign` event, the last condition matches everyone; drop it and say "contact history not tracked".
- A 7-day audience refills every week: use a period multiplier of about 4.3 for a monthly figure.
- Before quoting the value, apply the purchase-identity check from `funnel-leak-finder` (pattern F3): if purchases aren't linked to browsing identities, "didn't buy" is overstated.

### P7. New customers who haven't made a second purchase (Ran, with a 60-day outer window; same shape)

Plain English: first and only purchase 15–30 days ago.

```
customers matching count event purchase = 1
  and exists[event purchase in last 30 days] and not exists[event purchase in last 14 days]
```

- Use this for a second-purchase nurture. Keep its window next to P2's, not overlapping it (defaults: P7 15–30 days, P2 31–90 days), so the two don't double-count. If you widen one, move the other.

### P8. Large groups without consent (Ran)

Plain English: recent buyers or active visitors with no marketing consent, who could be asked for it.

```
customers matching exists[event purchase in last 365 days] and not has consent <category_id>
customers matching exists[event session_start in last 30 days] and not has consent <category_id>
```

- Use the `id` from `get_consent_settings` → `categories`. If the project has several categories, use the main marketing one and ask if unsure.
- Run the project-wide consent check in C3 first. If nobody has consent, don't report this as an opportunity to collect consent from everyone; report that consent isn't recorded in Engagement and ask where it's managed.
- The value is long-term (more customers you can message), so the ranking script marks it as 12-month value.

## Coverage checks (not EQL)

- `search_segmentations`: match names against each pattern's keywords (new, repeat, second, VIP, value, lapse, discount, voucher, affinity, cart, abandon, consent). `used_by` mixes many kinds of entry: `report_`, `metric_`, `segmentation_`, `funnel_`, `dashboard_`, `managed_tag_` and `campaign_design_`. **Only `campaign_design_<scenarioId>` means a scenario uses it.** In testing, only a handful of a production project's `used_by` entries were scenarios.
- Segmentation lists often contain **duplicate names**. Compare IDs, not names.
- `search_scenarios` (all statuses), then `trigger_types=["onevent"]` for cart and purchase flows. In a production test, every scenario was an on-site A/B split or a safety flow, with no lifecycle messaging at all. Confirm what a scenario does from its trigger and nodes (`search_scenario_nodes` via `call_tool`), not its name.
- `search_email_campaigns` for standalone campaigns. `search_sms_campaigns` can return 403.

## Avoid

- `select count event purchase_item by event purchase_item.category_level_1 ...` over 90 days or more: `very_high`.
- Any `sum` or `avg` of event values per customer group over a long window: `very_high`. Use AOV × counts (pattern V in `winback-opportunity`, 30-day window).
- Breaking down by email, phone, name, address, ID, URL or free-text properties.
