# Campaign QA

Pre-send QA for one standalone Bloomreach Engagement email or SMS/MMS campaign. It checks every A/B variant and translation for broken links, Jinja errors, compliance gaps (unsubscribe, postal address, consent, SMS opt-out, brand name, quiet hours, US state rules, Canada CASL), deliverability and spam risk, then the audience, schedule and split settings, and returns a GO / GO WITH CAUTION / NO-GO report with paste-ready fixes.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_email_campaigns`, `search_sms_campaigns`, `get_event_schema`, `get_customer_property_schema`, `search_aggregates`, `search_catalogs`, `search_recommendations`, `search_segmentations`, `list_project_variables`, `get_consent_settings`, `get_frequency_policies`, `list_customers`, `get_customer_properties` |
| **Other requirements** | Python 3 for `scripts/message_checks.py` (standard library only). Live link checks need a web-fetch or browser tool. |
| **Tested with** | Claude Code |
| **Maintainer** | @bloomreach |

The static checks are done by `scripts/message_checks.py` with thresholds in `references/rules.json`; the full check list is `references/message-checks.md`. `scenario-qa` and `engagement-send-preflight` ship identical copies of all three, so change them together.

## Example prompts

- "QA the Black Friday newsletter before we send it"
- "Is the weekend SMS campaign ready to go?"
- "Proof the April promo email: links, personalization, unsubscribe"

## Example output

```
🔴 NO-GO — Autumn sale · 2 blockers · 3 warnings · 1 nitpick · Email · 2 variants · 1 link not checked
Audience: everyone with newsletter consent (no filter) · Sends: when started

| # | Severity   | Variant   | Where   | Issue                                   | Fix |
|---|------------|-----------|---------|-----------------------------------------|-----|
| 1 | 🔴 Blocker | Variant A | body    | Hero links to brxcdn.co (near miss)     | Use https://brxcdn.com/… |
| 2 | 🔴 Blocker | all       | body    | No unsubscribe link                     | Add {{ email.unsubscribe }} to the footer |
| 3 | 🟡 Warning | Variant B | subject | {{ customer.first_name }} no fallback   | {{ customer.first_name | default('there', true) }} |
```

## Notes and limitations

- Standalone campaigns only. Scenarios go to `scenario-qa`.
- WhatsApp and RCS campaigns aren't covered by the script; check them by hand.
- The postal address and restricted-content checks are heuristics: the report says when a person needs to confirm.
- The North America SMS rules are as of October 2026 and aren't legal advice.
