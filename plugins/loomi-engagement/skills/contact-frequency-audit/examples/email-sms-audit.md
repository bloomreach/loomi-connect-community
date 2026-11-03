# Example: email and SMS frequency audit (illustrative)

**This example is illustrative.** The project and all figures are invented to show the output format. They do not come from a real project.

**Prompt:** "Are we sending people too many emails and texts? We're thinking about capping email at 3 a week."

## Contact frequency audit: example_retail_prod, 6 Oct to 2 Nov 2026 (28 days)

**Headline:** 15% of email recipients got 8 or more emails in four weeks, and their opt-out rate is four times that of customers who got one; SMS shows no fatigue.

### Email (10,000 recipients)
| Messages in 28 days | Per week | Customers | Share | Opt-out % | Clicked % | Note |
|---|---|---|---|---|---|---|
| 1 | 0.25 | 3,000 | 30.0% | 0.67 | 16.7 | reference |
| 2-3 | 0.5-0.75 | 3,000 | 30.0% | 0.50 | 23.3 | |
| 4-7 | 1-1.75 | 2,500 | 25.0% | 1.00 | 44.0 | |
| 8-11 | 2-2.75 | 900 | 9.0% | 2.78 | 50.0 | fatigue starts |
| 12-15 | 3-3.75 | 450 | 4.5% | 5.56 | 42.2 | |
| 16+ | 4+ | 150 | 1.5% | 6.67 | 40.0 | too few to judge |

**Recommended cap:** 7 emails per 28 days (about 1.75 a week), from the evidence (current default policy: 5 a week).
**Over the cap:** 1,500 customers (15% of recipients) got 8 or more. Your proposed cap of 3 a week would affect 150 customers (1.5%, measured at 16+, the nearest threshold above 13).

### SMS (5,000 recipients)
| Messages in 28 days | Per week | Customers | Share | Opt-out % | Clicked % | Note |
|---|---|---|---|---|---|---|
| 1 | 0.25 | 4,000 | 80.0% | 1.0 | — | reference |
| 2-3 | 0.5-0.75 | 900 | 18.0% | 1.0 | — | |
| 4+ | 1+ | 100 | 2.0% | 1.0 | — | too few to judge |

**Recommended cap:** 1 a week (rule of thumb; the data shows no fatigue).

### Findings (high first)
1. **High** Email: opt-outs rise from 0.67% to 2.78% at 8–11 emails in four weeks, and 15% of recipients are at or above that level. Set the default email policy to about 2 a week, and check which flows stack up for the heaviest recipients with `engagement-send-collision-check`.
2. **Low** SMS: no fatigue in the data; a rule-of-thumb cap of 1 a week keeps it that way.

**Coverage notes:** 25 EQL queries (all `medium`). Only 120 of the 400 customers who opted out of email in the window received email in it, so per-bucket opt-out rates understate the problem. Push not sent in the window.
