# Voucher pool health

Finds Bloomreach Engagement voucher pools that will run out or expire before the sends that use them. For each pool it counts available, assigned and redeemed codes (never printing a code), measures how many codes a day are handed out and says how that was measured, finds the scenarios, email and SMS campaigns and weblayers that hand out its codes, reads planned sends from the campaign calendar, and returns days of cover with a red, amber or green rating. It also flags empty pools a live flow still uses, pools nobody uses, and codes that expire before the campaign that hands them out. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_voucher_pools`*, `list_voucher_codes`*, `search_scenarios`, `search_scenario_nodes`*, `search_email_campaigns`, `search_sms_campaigns`, `search_banners`, `get_campaign_calendar`; optionally `get_event_schema`, `estimate_eql_cost`, `execute_analytics_eql` (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | None. Python 3 is optional, for the bundled script (standard library only) |
| **Tested with** | Claude Code, read-only, on a demo project (November 2026): `search_voucher_pools` list and one detail (for `used_by`), one page of `list_voucher_codes` (to confirm its fields), and one scenario named in a pool's `used_by`. The calendar shape comes from `engagement-send-collision-check`. `scripts/voucher_pool_health.py` tested on synthetic fixtures. Not run end to end, and not tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Will any of our voucher pools run out before Black Friday?"
- "How many codes are left in the welcome discount pool, and how long will they last?"
- "Which campaigns use the 'Spring 15' voucher pool?"
- "Do we have voucher pools nobody uses?"

See [examples/illustrative-voucher-health.md](examples/illustrative-voucher-health.md) for an example output. Its names and numbers are illustrative.

## How it works

1. Lists the pools, then fetches each pool's detail for its `used_by` list.
2. Measures the burn rate from the change in available codes since an earlier snapshot, or a voucher event counted with EQL, and says which.
3. Only when neither works, pages through a capped number of `list_voucher_codes` pages, saved to files, to count codes by assignment time. Codes are never shown, but paging brings them into the conversation, which is why it's the last resort.
4. Confirms each user's status and searches templates for `vouchers['<pool name>']` to find uses `used_by` misses.
5. Reads planned sends a week at a time from the campaign calendar.
6. [scripts/voucher_pool_health.py](scripts/voucher_pool_health.py) works out cover, planned demand and expiry, and rates each pool with the thresholds in [references/rules.json](references/rules.json).

## Notes and limitations

- **No expiry on codes.** `list_voucher_codes` returns only the code, status, assignment time and redemption time, so expiry checks need the date from the user.
- `list_voucher_codes` returns up to 1,000 codes a page with no status filter. The skill reads at most `max_code_pages` pages per pool and labels the burn rate a lower bound unless the pages cover the whole pool (page order isn't guaranteed).
- The calendar leaves out event-triggered flows, so a welcome flow's demand shows only in the burn rate.
- A pool's `used_by` can name weblayers and archived scenarios; the skill loads each user's status before calling a pool live or unused.
- `search_email_campaigns` and `search_sms_campaigns` can return HTTP 403; those kinds are reported as not checked.
