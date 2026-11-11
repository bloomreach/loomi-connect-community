# Example: two flows stacking emails on recent buyers

Illustrative only: the project, scenario IDs and all numbers are made up.

**Session 1 (5 November).** "Our unsubscribes keep climbing and people say we email too much. Find out which flows do it and fix it."

The measure stage finds email fatigue from 8 messages in four weeks: those customers unsubscribe at 0.9% against 0.2% for one message, and 14% of recipients are at or above that level. The sources stage finds the post-purchase cross-sell flow and the weekly browse-reminder flow both reaching recent buyers within a day, every week.

```
- F1 (open, high): channel email fatigued; 14% at 8+ in 28 days; opt-out 0.9% vs 0.2%. Next: engagement-send-collision-check
- F2 (chosen, high): scenario 6a3c00000000000000000011 collides with scenario 6a3c00000000000000000012; under 24h apart; reach 41,000 / 38,000. Next: engagement-scenario-builder
- F3 (open, low): email campaign 6a3c00000000000000000020 on unlimited-policy. Next: none
```

The cross-sell flow is running, so `engagement-scenario-builder` makes a new draft copy with a condition before its second email: only customers with fewer than 3 emails in the last 7 days go on (C1, create `scenario 6a3c00000000000000000013`). The user wants the cut made outright, so the test stage is skipped. `scenario-qa`: GO WITH CAUTION (the copy's frequency policy is `Default`; the user sets it back in Engagement). On 7 November the user switches the copy on and stops the original (C2, start `scenario 6a3c00000000000000000013`; C3, disable `scenario 6a3c00000000000000000011`, both live on 2026-11-07).

```
**Next:** recheck with contact-frequency-audit, not before 2026-12-05.
```

**Session 2 (8 December).** The ab-read-out stage is skipped (no test). The four weeks since the switch-on: 9% of recipients at 8+ emails, opt-outs there 0.6%: **improved**. `change-impact-tracker` finds project revenue **no clear effect** (-2% to +3%), so the cut didn't cost sales. F2 is done; F3 is still open for the user.
