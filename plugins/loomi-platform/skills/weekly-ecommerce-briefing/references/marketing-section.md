# Marketing section (Engagement)

A cut-down version of the `engagement-campaign-digest` method: enough for two or three lines in the briefing. For per-campaign rankings, use that skill.

## Calls

Run them one at a time. EQL (`estimate_eql_cost` and `execute_analytics_eql`) shares a limit of about one query every 3 seconds, so wait between calls and retry once after a "Too many requests" error.

1. **What ran:** `get_campaign_calendar` with `project_id`, `from_ts` and `to_ts` (Unix seconds) for this week.
   - Drop entries whose `status` is `draft` or `inactive`. The calendar lists their *planned* times even though nothing was sent.
   - Each entry is one send step (`action_name`) with `channel` and `results` (`reach`, `potential_reach`, `failed`).
   - Event-triggered flows (welcome, abandoned cart) don't appear in the calendar. The EQL below is the source of truth for what was sent.
   - Entries include `edited_by` (a person's name). Don't repeat it.
   - If it returns `error='timeout'`, retry with a narrower window.
2. **Email status mix, this week and last week.** For each period, estimate, then run:

   ```
   select count event campaign where .action_type = "email" by event campaign.status grouping top 15 since <start>Z until <end>Z
   ```

   On large projects this scores `high`; that's acceptable for this bounded, single-breakdown query. Don't run anything that scores `very_high`. The response has `data.rows[]`, each with `headers[0].value` (the status) and `values[0]` (the count). Empty `rows` means no campaign events in that period, not an error.
3. **SMS (only if the calendar shows SMS sends):** the same query with `.action_type = "sms"`.

That's 2–4 EQL queries plus their estimates. Tell the user how many you'll run.

## Rates

Use whichever send count exists: `sent`, otherwise `enqueued`, otherwise `delivered + bounces + failed`.

| Rate | Formula | Flag when |
|---|---|---|
| Delivery rate | delivered ÷ sends | below 97% |
| Click rate | clicked ÷ delivered | changes by more than 25% week on week |
| Bounce rate | (hard_bounced + soft_bounced) ÷ sends | over 2% |
| Unsubscribe rate | unsubscribed ÷ delivered | over 0.5% |
| Failed sends | failed ÷ sends, or any `failed` reach in the calendar | over 1% |

Projects spell statuses differently (`hard_bounced` or `hard_bounce`, `unsubscribed` or `unsubscribe`); count both. Counts are events, not unique customers. Opens are inflated by mail privacy features; prefer clicks.

## Revenue

Campaign revenue attribution isn't available from the `campaign` event. Don't estimate it. If the user needs it, the `engagement-campaign-digest` skill explains when a saved report or a UTM property on the purchase event can provide it.

## What to write

Two or three lines, for example:

> **Marketing:** 6 email sends (412k delivered, 98.9% delivery, 2.1% click rate, down from 2.6%). Bounces 0.4%, unsubscribes 0.2%. No SMS this week.

If nothing was sent: "No campaign sends recorded this week (calendar and campaign events are empty)."
