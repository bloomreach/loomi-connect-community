# Example: growing the email list

Illustrative only: the project, weblayer IDs and all numbers are made up.

**Session 1 (5 November).** "We can only email a third of our customers. Grow that."

`contactability-audit`, base = buyers in the last 365 days (about 52,000): 71% have an email address, 34% can be emailed with consent; net opt-ins have been about +600 a month. Two findings:

```
- F1 (chosen, high): channel email consent gap; 37% of the base has an address but no consent. Next: engagement-weblayer-builder
- F2 (open, medium): channel sms low reach; 6% reachable. Next: engagement-weblayer-builder
```

`onsite-experience-audit` finds no active weblayer that captures an email address, and one exit-intent pop-up on product pages: **no capture form**. The form goes on content and category pages instead.

`engagement-weblayer-builder` asks how the project records newsletter consent (a scenario on the `subscribe` action) and the hard ID (`email_id`), and writes a slide-in form with two variants: a 10% welcome offer and no offer. The user pastes it into an inactive weblayer, `banner 6a3c00000000000000000001`. `engagement-weblayer-qa` returns GO WITH CAUTION (the privacy link couldn't be loaded from the checker). The user launches it on 7 November:

```
- C1: start banner 6a3c00000000000000000001 on 2026-11-07 (in place, live)
**Next:** read-out with engagement-experiment-readout, not before 2026-11-21.
```

**Session 2 (24 November).** `engagement-experiment-readout`: 18,200 and 18,050 viewers, sign-ups 1.1% without the offer and 2.3% with it, purchases flat: **Call the winner**. The user sets the offer variant to 100% (C2, update).

**Session 3 (8 January).** The recheck: email reach 34% → 37% of the base; December's net opt-ins +1,450, against about +600 a month before. A December campaign also asked for consent, so part of it isn't the form: **reach grew**.
