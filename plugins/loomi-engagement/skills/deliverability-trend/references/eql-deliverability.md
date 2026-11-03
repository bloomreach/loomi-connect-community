# EQL for the deliverability trend

Every query counts `campaign` events (one per message outcome) and returns aggregate counts only. Replace `<start>` and `<end>` with the window's first day and the day after its last (UTC, ending in `Z`). Estimate each one with `estimate_eql_cost` before running it, and space EQL calls at least 3 seconds apart.

Status labels:
- **Ran:** executed in live, read-only testing (November 2026) on a demo project of about 1.2 million customers and 10 million events, where it scored `high`.
- **Same shape:** a different property in the same position as a query that ran; not run itself.

## What the campaign event holds

| Property | Use |
|---|---|
| `action_type` | Channel. Tested values: `email`, `sms`, `mobile notification`, `browser notification`, `whatsapp`, `ads` (with spaces, not underscores). Check the project's own values in the daily query's response before filtering. |
| `status` | Outcome. On the tested project email had `enqueued`, `delivered`, `opened`, `clicked`, `hard_bounced`, `soft_bounced`, `complained` and `unsubscribed`, and no `sent`. Other projects and older documentation use `hard_bounce` and `unsubscribe`; `references/rules.json` maps both. |
| `sender`, `sending_ip`, `integration_name` | Who sent it and through which integration. They can be empty: on the tested project `sender` was null on every event. |
| `campaign_id`, `campaign_name` | The scenario or one-off campaign. A scenario's events carry the scenario's ID. |
| `campaign_trigger` | Present in the schema, but null on every tested event, so it can't tell scenarios from one-off campaigns. Use `campaign_id` against `search_scenarios` instead. |
| `recipient`, `ip`, `user-agent` | Personal data. **Never break down by them.** |

## The queries

**1. Daily trend by status (Ran, high).** One query gives the whole trend; the script sums days into Monday-to-Sunday weeks.

```
select count event campaign where .action_type = "email" by row event campaign timestamp grouping top 92 format year month day by column event campaign.status grouping top 15 since <start>Z until <end>Z
```

- Live testing used `in last 91 days` at the end; `since … until …` in the same place is the documented form for a fixed window.
- Day headers are Unix seconds at **local midnight in the project's time zone**, so a day can show as 23:00 UTC the day before, and a daylight-saving change makes one day 25 hours. The script handles both.
- Days with no email are missing from `rows`. Columns list every status in the project, including ones other channels use (`sent`, `success`), with zeros.

**2. By sending domain (Ran, high).**

```
select count event campaign where .action_type = "email" by row event campaign.sender grouping top 15 with null by column event campaign.status grouping top 15 since <start>Z until <end>Z
```

If the only row is `null`, the project doesn't record a sender: say so and skip it. The script reduces addresses to their domain; never repeat a full sender address.

**3. By sending integration (Same shape as 2).** Replace `campaign.sender` with `campaign.integration_name`. Useful when the project sends through more than one ESP or IP pool.

**4. By campaign (Same shape as 2).** Replace `campaign.sender` with `campaign.campaign_id` and use `grouping top 30 with null`. With a saved `search_scenarios` list, the script splits scenarios from one-off campaigns and lists the campaigns with the most bounces, complaints and unsubscribes.

**5. New vs established audience (Ran, high).** Events from customers with no delivered email before the window, a proxy for newly added or imported addresses:

```
select count event campaign where .action_type = "email" by event campaign.status grouping top 15 customers matching not exists[event campaign where .action_type = "email" and .status = "delivered" until <start>Z] since <start>Z until <end>Z
```

- `customers matching` must come **before** `since … until …`; after it is a parse error.
- Use the delivered status name the project uses. The script works out "established" as the window total minus this.
- `estimate_eql_cost` adds "expensive customer filter" but it stayed `high`.

**6. One spike week by campaign (Same shape as 2).** For a week the script flags (`<monday>` to the Monday after):

```
select count event campaign where .action_type = "email" by row event campaign.campaign_name grouping top 20 by column event campaign.status grouping top 15 since <monday>Z until <next monday>Z
```

## Budget

Query 1 is required. Queries 2–5 are one each, and 6 is one per spike week. A full run is 5–8 queries, all `high` on large projects. Tell the user the plan before starting, and ask before going beyond 6. Never run a query that scores `very_high`: shorten the window (60 days) or drop a breakdown.
