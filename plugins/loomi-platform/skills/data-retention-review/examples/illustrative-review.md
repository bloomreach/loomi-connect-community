# Example: data retention review

Illustrative output for a made-up project. Every name, period and number is invented.

**Prompt:** "Do our data retention rules break any segments or reports?"

---

## Data retention review: Example Store (production), 2026-11-04

> Not legal advice. This review compares retention with what the project's analytics read. Retention periods depend on your legal bases and obligations: check changes with your data protection lead or legal counsel.

**Verdict:** 2 high, 6 medium, 4 low. A live segmentation looks back two years at purchases kept for one, and campaign events are deleted after a day, so deliverability and frequency analyses can't run.

**Retention now:** default off (kept for ever); overrides: campaign 1 day, purchase 1 year, page_visit 30 days, session_start 5 years.

### Changes to consider
| # | Priority | Event or property | What's wrong | Change to consider |
|---|---|---|---|---|
| 1 | High | purchase | Segmentation "Bought in the last two years" looks back 730 days; purchase is kept 365 days | Shorten the window to 12 months, or keep purchase 2 years |
| 2 | High | birth_date, partner_birthday | Look like special-category or identity data; event retention never removes them | Confirm they're needed and lawful; agree an anonymisation routine |
| 3 | Medium | campaign | `deliverability-trend` and `contact-frequency-audit` read 28–90 days; campaign is kept 1 day | Keep campaign events at least 90 days |
| 4 | Medium | purchase | `winback-opportunity` reads up to 730 days | Expect win-back bands past a year to be empty |
| 5 | Medium | newsletter_signup | Kept for ever, carries an email property, nothing reads it | Set a retention period |
| … | | | | |
| 12 | Low | consent | Kept for ever; no window found reads it | Usually keep: consent history is evidence. Confirm with legal |

### Events: kept vs read
| Event | Kept | Rule | Longest window read | Definitions reading it |
|---|---|---|---|---|
| purchase | 365 days | override | all time | 4 |
| page_visit | 30 days | override | 90 days | 1 |
| campaign | 1 day | override | 90 days (skills) | 0 |
| session_start | 1825 days | override | 90 days | 0 |

### Personal customer properties
High: birth_date, partner_birthday. Medium: email, first_name, phone. Low: city, zip. Data Manager retention covers events only, so these stay until a profile is anonymised or deleted.

### Not checked
Scenario waits and conditions; exports and integrations; 14 reports beyond the detail limit.
