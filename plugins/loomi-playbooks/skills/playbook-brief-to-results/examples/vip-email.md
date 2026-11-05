# Example: a VIP email from a brief

Illustrative only: the project, campaign IDs and all numbers are made up.

**Session 1 (5 November).** "Here's the brief for the VIP early-access email. Build it, check it, and tell me how it did."

`engagement-email-builder` offers three subject lines, builds the HTML and, after its yes, creates the draft and reads it back:

```
- C1: create email campaign 6a2b00000000000000000002 on 2026-11-05 (in place)
```

build-sms is skipped.

`campaign-qa` returns NO-GO: one product link 404s. The user fixes the link in the Engagement HTML editor; QA again: GO. The user sets the send for 11 November and starts it. The qa stage is recorded `scheduled`, the scheduled send goes in the change log as a change from `engagement-ui` (C2, start `email campaign 6a2b00000000000000000002`, live on 2026-11-11), and the digest gets `--not-before 2026-11-18`.

**Session 2 (10 November).** The preflight shows the campaign GO, and one other send NO-GO (not this run's). The collision check finds a promo email to an overlapping segment four hours earlier on 11 November; the user moves the promo to 13 November in Engagement: `collisions_fixed`.

```
**Next:** digest with engagement-campaign-digest, not before 2026-11-18.
```

**Session 3 (18 November).** The digest for the week of 10 November: the VIP email reached 18,400, 99.1% delivered, 6.2% clicked against 3.4% for the week, 0.1% unsubscribed, 12,600.00 revenue attributed. Two findings go into the file for the next brief:

```
- F1 (open, medium): email campaign 6a2b00000000000000000002 keep the early-access angle; click rate 6.2% vs 3.4% for the week. Next: engagement-email-builder
- F2 (open, low): email campaign 6a2b00000000000000000002 try a shorter subject; opens 1.8 points under the week. Next: engagement-email-builder
```
