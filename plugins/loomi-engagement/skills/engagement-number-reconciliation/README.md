# Engagement number reconciliation

Works out why two numbers that should agree don't, and which one answers your question. For example: an AI answer vs a saved report, a segment size vs a filter, Bloomreach vs your BI tool, ESP or warehouse export, or this week's report vs last week's.

- **Collects both definitions word for word** (with any email, phone, name or ID replaced by `<email>` or `<id>`) and lines them up: what is counted, which statuses, both window bounds and the time zone, which customers, and what "subscribed" means.
- **Checks the usual causes:** a dropped filter (the number is the whole customer base), history that starts later than the window, empty filter fields, one purchase event per order status or repeated order IDs, consent category vs a subscribe property, time zones, enqueued vs delivered, per send vs per customer rates, first-ever vs any buyers, and first-match segments.
- **Rebuilds both definitions in EQL**, side by side in one query where it can, so the rows add up to the gap.
- **Returns a table** of number, definition, source and as-of time, the cause with how much of the gap it explains, and which number to use. Often both are right for different questions; when one is simply wrong, it says so.

It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_project_overview`, `search_reports`, `calculate_report`, `search_segmentations`, `search_customer_filters`, optionally `search_aggregates` and `search_expressions`, `get_consent_settings` (via `search_tools` and `call_tool`), `get_event_schema`, `get_customer_property_schema`, `estimate_eql_cost`, `execute_analytics_eql` |
| **Other requirements** | None |
| **Tested with** | Claude Code, November 2026, read-only against a sandbox project. Reproduced seven disagreements end to end: consent vs a subscribe property, a dropped filter, history that starts later in one source, a UTC vs UTC+2 day, send statuses and per send vs per customer open rates, a first-match segmentation's catch-all segment, and repeated order IDs; plus a saved report read with `calculate_report` and matched by an EQL rebuild. The checks in [references/usual-suspects.md](references/usual-suspects.md) marked "Ran" were executed. Not tested against a real external export, and not in an OpenAI client |
| **Maintainer** | @pavelsafarikbr |

## Example prompts

- "The AI says 12,650 July buyers are subscribed, our segment says 6,130. Which is right?"
- "Our BI tool shows 8,000 new customers in March, Bloomreach shows 36. Why?"
- "This segment shows 40 people, but when I check the same filter I get everyone."
- "Our ESP says we sent 39,000 emails, the Bloomreach report says 41,000."
- "Last week's report said revenue was 1.2M, this week's says 1.1M for the same week."

See [examples/consent-vs-property.md](examples/consent-vs-property.md) for an anonymised answer, with the other disagreements the test reproduced.

## How it works

1. **Collect:** both numbers with their label, source, as-of time and definition, verbatim. Saved Engagement reports, segmentations and filters are read by ID; for an AI answer it asks for the query; for an external tool it asks for the export settings.
2. **Line up:** both definitions on one grid (unit, event and status, value, window and time zone, audience, identity, consent, source and freshness, grouping rules), each row marked same, different or unknown.
3. **Check:** the usual suspects that fit, cheapest first, from [references/usual-suspects.md](references/usual-suspects.md).
4. **Rebuild:** both definitions in EQL, cost-estimated first, ideally as two metrics in one query broken down by the property that separates them.
5. **Decide:** restates the real question and says which number answers it, or that both do for different questions.

## Notes and limitations

- It can only query Engagement. For a number from another system, it rebuilds that system's stated definition on Engagement data; a gap that remains lies in the other system's data (history, refresh time, identity), which it names but can't measure.
- A number with no visible definition (an AI answer that doesn't show its query) can't be fully checked. The skill says so and rebuilds the likely definitions to see which matches.
- `calculate_report` returns Engagement's cached result, which can lag a live EQL rebuild by hours or days. Small gaps (1–2%) between a live rebuild and an older number are usually new data.
- It never reads individual customers, even to size a segment: segment sizes are rebuilt in EQL, following the first-match rule.
- EQL is limited to about one query every 3 seconds across the whole Engagement instance, shared with other users; event counts and sums are often rated "high", and the skill asks before running those.
