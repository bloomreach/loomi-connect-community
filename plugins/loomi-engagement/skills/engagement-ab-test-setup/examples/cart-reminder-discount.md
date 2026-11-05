# Example: a discount test in a cart reminder flow

Illustrative only: the project, scenario and node IDs and all numbers are made up.

**Prompt:** "A/B test a 10% discount in the cart reminder email of our abandoned cart flow."

The flow is a draft with five steps:

```
0 on-event-trigger (cart_update) → 1 wait 4 hours → 2 email "Cart reminder" → 3 wait 1 day → 4 SMS "Cart SMS"
```

The split goes on the connection 1 → 2. The user picks a message test, 50/50, "Control" and "10% off", variant B copied from the control (they'll add the discount in Engagement), and conversion (a purchase within 3 days) as the metric. `engagement-scenario-performance` shows about 420 customers a day reach the email, 4% of whom buy.

```
python3 <skill>/scripts/ab_test_duration.py --baseline-rate 0.04 --entrants 12600 --days 30 --control-share 50 --variant-share 50 --out work/duration.json
```

| Lift to detect | Customers needed (control / variant) | Days needed | Run for |
|---|---|---|---|
| +5% | 308,612 (154,306 / 154,306) | 735 | 735 days |
| +10% | 78,951 (39,476 / 39,476) | 188 | 189 days |
| +20% | 20,633 (10,317 / 10,317) | 50 | 56 days |

A +20% lift is plausible for a discount, so the test is planned for 8 weeks, ending 31 December.

```
## A/B test plan: Cart reminder flow (Example Retail, draft)

**Test:** message: the reminder email with and without 10% off
**Split point:** after step 1 (wait-action), before step 2 (send-email-action, Cart reminder)
**Branches:** Control 50% → today's email · 10% off 50% → step 6, a copy of the email to edit
**Metric:** conversion (purchase within 3 days); guardrail unsubscribes
**Size:** about 420 customers a day reach the split; about 10,300 per branch to detect +20%; about 50 days → run until 2026-12-31
**Change:** 2 steps added (split 5, variant B 6); connection 1:1 → 2 removed; 4 connections added
**Warnings:** Variant B is an exact copy of the control message. Change its content in Engagement before the flow is switched on.

Nothing runs until you switch it on in Engagement. Shall I add this split to Cart reminder flow in Example Retail?
```

After "yes": the scenario is fetched again (unchanged), updated, read back and verified **in place**. The hand-over: add the discount to step 6 in Engagement, run `scenario-qa`, switch the flow on, and run `engagement-experiment-readout` on split 5 ("Control" vs "10% off") after 31 December.
