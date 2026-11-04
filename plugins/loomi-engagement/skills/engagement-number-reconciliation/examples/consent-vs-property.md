# Example: two "subscribed" counts (anonymised)

**Based on a real read-only test run** on a sandbox project in November 2026. Numbers are rounded to the nearest 10; property and category names are the generic ones the skill would find in many projects. 2 EQL calls (1 estimate, 1 query), plus `get_project_overview`, `get_consent_settings` and the customer property schema.

**Prompt:** "The AI assistant told me 12,650 of our July buyers are subscribed to the newsletter. Our segment of July buyers with email_subscribe = subscribed shows 6,130. Which one is right?"

---

**Both are right for different questions.** 12,650 July buyers hold valid newsletter consent, which is what decides who may be emailed. 6,130 have the `email_subscribe` property set to `subscribed`, an imported flag that doesn't follow consent. For "who can we email", use 12,650.

| | Number | Definition | Source | As of | Rebuilt in EQL |
|---|---|---|---|---|---|
| A | 12,650 | Customers with a completed purchase 1–31 July 2026 (UTC) and valid consent in the `newsletter` category | AI answer (its query was shown) | 2026-11-03 | 12,650 |
| B | 6,130 | Customers with a completed purchase 1–31 July 2026 (UTC) and `email_subscribe = "subscribed"` | Saved segment | 2026-11-03 | 6,130 |

Same unit (customers), same purchases, same window: the only different row in the definition grid is consent.

**Why they differ** (gap 6,520)
| Cause | Explains | Evidence |
|---|---|---|
| Consent holders whose property is empty | +4,900 | `email_subscribe` has no value, newsletter consent valid |
| Consent holders whose property says `unsubscribed` | +2,070 | property `unsubscribed`, newsletter consent valid |
| Property says `subscribed`, but no valid consent | −450 | property `subscribed`, no consent |
| **Total** | **6,520** | 4,900 + 2,070 − 450 |

**Use:** 12,650 for "who can we email". The property disagrees with consent for about 7,400 of these buyers, including 450 flagged `subscribed` whom any send that checks the newsletter consent would leave out.
**Unexplained:** nothing.
**Checks:** neither number equals the project's 75,000 customers (no dropped filter); history starts in 2023, well before July.
**Queries run** (1, as of 2026-11-03 14:45 UTC):

    select count customers, count customers matching (has consent newsletter) by customer.email_subscribe grouping top 3 with null customers matching exists[event purchase where .purchase_status = "success" since 2026-07-01T00:00:00Z until 2026-08-01T00:00:00Z]

**Next:** rebuild the segment on the newsletter consent category instead of the property (`engagement-segment-builder` can do it after you confirm), or ask whoever imports `email_subscribe` whether it's still maintained.

---

## Other causes the same test reproduced

| Disagreement | Numbers (rounded) | Cause |
|---|---|---|
| "UK customers with SMS consent" from an AI answer vs the UK segment | 75,000 vs 21,900 | The first number equals all customers in the project: the filter was dropped |
| "First-time buyers in March" from a warehouse report vs Engagement | 8,260 vs 36 | The warehouse history starts four days before March, so returning customers look new. 8,430 bought in March in total |
| Orders on 1 July, dashboard vs BI tool | 267 vs 264 | UTC day vs a UTC+2 day |
| Newsletter open rate, report vs AI answer | 69% vs 88% vs 47% | Opens per delivered send, unique openers per unique recipient, and unique openers per delivered send |
| "Rest" segment in a segmentation vs the same filter alone | 40 vs 75,000 | Segments are first-match-wins; the empty catch-all filter alone matches everyone |
| Lifetime orders vs distinct orders | Two order IDs with over 1,100 events each | Repeated order IDs: events counted as orders |
