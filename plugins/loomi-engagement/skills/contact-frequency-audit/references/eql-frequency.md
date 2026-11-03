# EQL for the contact frequency audit

EQL can't break customers down by how many events they had, so the distribution is built from **cumulative counts**: one customer count per threshold ("received at least K"), and the script turns them into buckets ("received 4 to 7"). Every query returns one aggregate number; none lists customers.

Replace `<start>` and `<end>` with the window's first day and the day after its last (UTC, ending in `Z`), and `<action_type>` and `<received>` with the channel's values from `channel_filters` in `references/rules.json`, checked against the project (query 0). Estimate each query with `estimate_eql_cost` first, and space EQL calls at least 3 seconds apart.

Status labels:
- **Ran:** executed in live, read-only testing (November 2026) on a demo project of about 1.2 million customers.
- **Same shape:** follows a form that ran, with a documented operator; not run itself.

## Getting one number

A `select` needs a `by`. Break down by a **low-cardinality, non-personal** customer property (country or language, from `get_customer_property_schema`), keep nulls, and add up every row, including `null`, `""` and `{"type": "other"}`. An empty `rows` list means 0. **Never** use email, phone, name or any ID property: `grouping top 1` on such a property returns a real customer's value.

## The queries

**0. Channels and statuses in use (Ran, high).** Run once, for the window:

```
select count event campaign by row event campaign.action_type grouping top 10 by column event campaign.status grouping top 20 since <start>Z until <end>Z
```

On the tested project: email had `delivered` (plus `enqueued`, `opened`, `clicked`, `hard_bounced`, `soft_bounced`, `complained`, `unsubscribed`); `sms`, `mobile notification` and `browser notification` had only `sent` and `clicked`; `whatsapp` had `sent`. Push channels are spelled with a space. Use `delivered` for email, and `sent` where a channel has no `delivered`.

**1. Recipients with at least K messages (Ran, medium).** One per threshold:

```
select count customers by customer.<property> grouping top 3 with null customers matching count event campaign where .action_type = "<action_type>" and .status = "<received>" since <start>Z until <end>Z >= <K>
```

- The `since … until …` window inside the count **is** applied (a 7-day window returned about a quarter of the 28-day count), although `estimate_eql_cost` still lists "lifetime date range" as a cost factor.

**2. Of those, who opted out (Same shape as 1 + 4).**

```
select count customers by customer.<property> grouping top 3 with null customers matching count event campaign where .action_type = "<action_type>" and .status = "<received>" since <start>Z until <end>Z >= <K> and exists[event campaign where .action_type = "<action_type>" and .status is in ["unsubscribed", "complained"] since <start>Z until <end>Z]
```

- `is in` needs at least two string values. Use the project's status names (`optout_statuses` in rules.json).
- The same query with `.status = "unsubscribed"` alone ran and returned no rows on the demo project: its unsubscribers had no delivered email in the window. Query 4 catches that.

**3. Of those, who clicked (Same shape as 2).** Replace the `exists[...]` status with `.status = "clicked"`.

**4. Everyone who opted out in the window (Ran, medium).** For the coverage check:

```
select count customers by customer.<property> grouping top 3 with null customers matching exists[event campaign where .action_type = "<action_type>" and .status is in ["unsubscribed", "complained"] since <start>Z until <end>Z]
```

**5. The reachable base (optional).** For "share of the base over the cap", count customers with the channel's consent: `customers matching has consent <category_id>` (the category from the project's consent settings). Without it, shares are of recipients.

## Saving the results

Save each result in one folder in your working folder, named so the script can read the whole folder with `--dir`:

| Query | File name |
|---|---|
| 1 | `<channel>_all_<K>.json`, e.g. `email_all_4.json` |
| 2 | `<channel>_optout_<K>.json` |
| 3 | `<channel>_engaged_<K>.json` |
| 4 | `<channel>_optout_total.json` |
| 5 | `<channel>_base.json` |

Use `email`, `sms` and `push` as channel names (no underscores).

## Budget

Per channel: one query 1 per threshold, the same again for 2 and for 3, plus one query 4: with the default six email thresholds that is 19 queries, about two minutes at the EQL rate limit. To keep it down:

- run query 1 for every threshold first; drop higher thresholds whose count is under `min_bucket_customers` (the last kept one becomes the open-ended bucket);
- skip query 3 when the user only cares about opt-outs, or for channels without click tracking;
- do one channel at a time, email first, and ask before starting the next.

Tell the user the number of queries before starting. Never run one that scores `very_high`.
