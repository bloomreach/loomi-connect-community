# Example: Black Friday

Illustrative only: the account, project, pool and campaign IDs and all numbers are made up.

**Session 1 (5 November).** "Get us ready for Black Friday, 27 November to 1 December."

The run starts with the event dates: the preflight is due from 20 November and the review from 4 December. The planner ranks five campaign ideas and finds one clash on 27 November. Two landing collections are defined ("gifts for him", "winter boots"). The readiness check and voucher check add findings:

```
- F1 (open, high): rule 900310 expires mid-event; ends 2026-11-28 23:59, only event rule on its query. Next: discovery-rule-cleanup
- F2 (open, high): pool 12 runs out before the event; 1,800 codes left, 310 a day, 4,000 planned recipients. Next: None
- F3 (open, medium): campaign 8810 clashes with campaign 8812; same segment, 3 hours apart on 2026-11-27. Next: engagement-send-collision-check

**Next:** preflight with engagement-send-preflight, not before 2026-11-20.
```

The user extends the rule with `discovery-rule-cleanup` and imports more codes, then marks F1 and F2 done.

**Session 2 (21 November).** The preflight checks 9 sends in the event window: 7 GO, 1 GO WITH CAUTION (a missing unsubscribe link in one SMS step), 1 NO-GO (a draft still scheduled). The collision check confirms F3 and finds no other overlap.

**Session 3 (5 December).** The review compares 27 November to 1 December with the five days before: revenue up 64%, three quarters of it from traffic, and the "gifts for him" collection among the top contributors. Outcome **explained**.
