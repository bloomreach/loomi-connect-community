# Engagement send preflight

One pre-send check of everything a Bloomreach Engagement project is about to send in the next few days: standalone email and SMS campaigns and scenario steps on the campaign calendar, plus live event-triggered flows changed recently. Each send gets the same content checks as `campaign-qa` and `scenario-qa` (links, Jinja, unsubscribe, address, consent, SMS opt-out and quiet hours, spam risk) and a GO / GO WITH CAUTION / NO-GO verdict. You get one list, soonest send first, plus collisions and busy days.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_campaign_calendar`, `search_email_campaigns`, `search_sms_campaigns`, `search_scenarios`, `search_segmentations`, `get_frequency_policies` |
| **Other requirements** | Python 3 for the scripts (standard library only). Live link checks need a web-fetch or browser tool. |
| **Tested with** | Claude Code |
| **Maintainer** | @bloomreach |

`scripts/message_checks.py`, `references/rules.json` and `references/message-checks.md` are identical copies of the files in `campaign-qa` and `scenario-qa`, and `scripts/find_collisions.py` of the one in `engagement-send-collision-check`; change them together. `scripts/send_window.py` works out the calendar weeks and recently edited live flows (`references/preflight-rules.json`), and `scripts/preflight_report.py` joins the calendar with the findings.

## Example prompts

- "What's going out this week, and is it all ready?"
- "Preflight tomorrow's sends"
- "QA everything scheduled for Black Friday week"

## Example output

```
🔴 NO-GO for 2 of 9 sends · Tue 4 – Mon 10 Nov · 1 caution · 5 go · 1 not checked · 3 links not checked

Fix before it sends
| When (UTC)      | Send                 | Channel | Blockers | What to fix |
|-----------------|----------------------|---------|----------|-------------|
| Tue 4 Nov 08:00 | Autumn promo         | Email   | 3        | No unsubscribe link; [First Name] in the body; hero links to brxcdn.co |
| Tue 4 Nov 11:00 | Cart flow / Cart push| Push    | 2        | Push body empty; title still "Notification title" |
```

## Notes and limitations

- Lighter than `campaign-qa` and `scenario-qa`: no rendering against sample profiles and no scenario flow checks. Hand NO-GO sends to them.
- The calendar leaves out event-triggered flows, so only live flows edited in the last 7 days are checked unless you ask for all of them.
- WhatsApp, RCS, web push, app inbox and webhook sends are listed but not checked.
- Calendar times are UTC.
