# Example: journey health check

Based on a live, read-only test run against a sandbox project. Flow and step names are relabelled and numbers are rounded.

## Prompt

> Which of our live journeys aren't working right now?

## Output

```
## Journey health: 10 live flows, 20 Oct – 2 Nov (vs 6–19 Oct)

**Headline:** 4 problems to fix now and 2 to review, across 8 of the 10 flows. One flow wasn't fully sized, and one has no message step.

| # | Severity | Flow | Step | What's wrong | Evidence | Fix |
|---|---|---|---|---|---|---|
| 1 | Action | Loyalty tiers | Gold newsletter (email) | Deliveries stopped after the first week | 2,000 → 0 delivered; the other email steps fell 96–98% | The "received at most 12 times" condition checks "has received in 365 days" with no count, so each customer gets the flow once a year: rebuild it as a count of deliveries ≤ 12 |
| 2 | Action | Session follow-up test | Unnamed email | Nobody has ever received it | Every session start triggers it; over 30 days, 47,000 suppressed and 0 delivered; reason: no consent for the step's category "other" | Stop the flow, or use the consent category the audience has |
| 3 | Action | Return follow-up | Return email | Active 3 weeks, never sent | Its condition needs a product property that 0 of 75,000 customers have; the flow that sets it triggers on cart adds, and no cart events arrived in 14 days | Fix cart tracking first, then check the property fills |
| 4 | Action | Birthday offer (5 active flows) | Birthday email | None of them sent in 28 days | 54,000 customers have a birth date; the first condition is a date expression | Check "Birthday in 7 days" in the condition preview, then keep one flow active so customers don't get five emails |
| 5 | Review | Loyalty tiers | Silver newsletter (email) | 12% failed to render | 25 of 210 not queued; reason: recommendation timeout | Ask for fewer items or add a fallback engine |
| 6 | Review | Loyalty tiers | Both SMS steps | Placeholder setup in a live flow | Step names say "placeholder"; sender name looks like test text | Set the real sender and rename the steps |

**Healthy:** none with enough volume in the last 14 days.
**Not checked:** one weekly flow passes its first four conditions for about 220 customers but sent nothing; its later conditions weren't sized (open its run history in Engagement). One flow has no message step (it only updates a property), so silence is expected.
```
