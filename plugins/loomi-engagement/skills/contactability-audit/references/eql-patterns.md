# EQL patterns for the contactability audit

Every query here returns **aggregate counts**. None of them lists or reads individual customers.

Status labels:
- **Ran:** executed in live testing (November 2026, a demo project of about 600,000 customers), with the cost rating it got.
- **Parsed:** accepted by `estimate_eql_cost` but not executed.
- **Shape:** not tried in this skill; the same operators ran in `segment-opportunity-finder` or `winback-opportunity`.

Replace `email`, `phone`, `purchase`, `total_price` and the category IDs with the project's own, from `get_customer_property_schema`, `get_event_schema` and `get_consent_settings`. `estimate_eql_cost` doesn't check names, so a typo only shows up as a zero.

## Getting a total

A `select` needs a `by` clause. Break down by a **low-cardinality, non-personal** customer property (country or language, from `get_customer_property_schema`); **never** email, phone, name or any ID property, because `grouping top N` on such a property returns real customers' values, include nulls, and **add up every row**, including `null`, `""` and `other`. An empty `rows` list means 0. The script does this when you pass the saved result as a file.

```
select count customers by customer.<country_or_language> grouping top 3 with null customers matching <conditions>
```

Write `<base>` below as the base conditions, in brackets, and use parentheses whenever you mix `and` and `or`.

## Base

| Base | `customers matching ...` | Status |
|---|---|---|
| Buyers in the last 365 days (default) | `exists[event purchase in last 365 days]` | Shape |
| Known customers | `customer.email has value or customer.phone has value` | Shape |

Anonymous visitors usually outnumber known customers many times over, so never use "all customers" as the base: every share would look tiny.

## Channels

| Count | `customers matching ...` | Status |
|---|---|---|
| Email identifier | `(<base>) and customer.email has value` | Shape |
| Email reachable | `(<base>) and customer.email has value and has consent <email category id>` | Ran without a base: `medium` |
| SMS identifier | `(<base>) and customer.phone has value` | Shape |
| SMS reachable | `(<base>) and customer.phone has value and has consent <sms category id>` | Shape (same as email) |
| Push identifier | `(<base>) and customer.<push token property> has value` | Shape; only if the schema has a push token property |
| Any channel | `(<base>) and ((customer.email has value and has consent <email id>) or (customer.phone has value and has consent <sms id>))` | Shape |

- `has consent <id>` takes the category `id` from `get_consent_settings`, not its display name.
- **Categories aren't tied to channels.** A project can have `newsletter`, `sms`, `Automated_Campaigns` and more. Pick the category each channel's marketing messages use (the `consent_category` on send nodes in scenarios is the best evidence), and ask the user if unsure.
- **`general_consent`:** when `general_consent.<channel>` is `true`, that channel can send without a category, so the reachable count for it is the identifier count. Say so.
- **Push:** push tokens aren't always customer properties. If `get_customer_property_schema` has nothing that looks like a push token (names with `push`, `token`, `fcm` or `apns`), report push as "can't be measured from customer data" rather than zero.
- **Consent kept elsewhere:** shop-platform integrations can keep marketing consent as customer properties (seen on a demo project: an `accepts_marketing` flag and per-channel `*_marketing_consent` properties next to the Engagement categories). If `has consent` is empty for every category, measure from those properties instead, and say which you used.

## High-value customers who can't be reached

```
... customers matching sum event purchase.total_price >= <threshold>
... customers matching sum event purchase.total_price >= <threshold> and not (customer.email has value and has consent <email id>) and not (customer.phone has value and has consent <sms id>)
```

- The second **Ran** (`medium`). The first is the same shape without the reach conditions.
- Pick the threshold with the user: about 3 × AOV of lifetime spend, or their own VIP definition. A prediction or an RFM property works too (`customer.rfm_monetary_group = "<top group>"`), if the project has one that's filled.

## Consent over time (opt-ins and opt-outs by month)

```
select count event consent by row event consent timestamp grouping top 6 format year month by column event consent.action grouping top 5 with null since <first day, 6 months ago>T00:00:00Z until <first day of this month>T00:00:00Z
```

- **Ran** (`high`). Without `grouping top 6` on the timestamp it was `very_high`: always cap the months.
- Rows are month buckets as Unix timestamps at local midnight in the project's time zone (so an hour or more off the UTC month start). Months with no events are left out. The script turns the timestamps into months.
- Columns are the `action` values. In testing they were `accept` and `reject`; the script counts the values listed in `rules.json` and reports the rest as "other".
- Add `where .category = "<id>"` after `event consent` in the metric to look at one category.

## Consent events by category

```
select count event consent by row event consent.category grouping top 20 with null by column event consent.action grouping top 5 with null in last 180 days
```

- **Ran** (`high`). The same query over 365 days was `very_high`: keep it to 180 days.
- Category values are the category `id`s. A `null` row with zeros can come back: ignore it.

## Who holds a quiet category

For each defined category with no consent events in the window:

```
... customers matching has consent <category id>
```

**Shape** (`has consent` ran in the reachability query). Zero holders and zero events means the category is defined but never used.

## Avoid

- Timestamp breakdowns without `grouping top N`, and consent-event breakdowns over 365 days: `very_high`.
- Breaking down by email, phone, name, address, ID or any free-text property.
- `list_customers` or `list_customers_in_segment` to "check" a count: this skill reports counts only.
