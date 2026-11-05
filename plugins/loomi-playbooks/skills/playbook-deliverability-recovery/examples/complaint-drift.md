# Example: complaints drifting up

Illustrative only: the project, scenario IDs and all numbers are made up.

**Session 1 (5 November).** "Our spam complaints keep creeping up. Find out why and fix it."

The trend stage finds complaint drift: the last four weeks pooled at 0.14% against 0.06% before, mostly on one-off campaigns to recipients who haven't opened in six months. The frequency audit finds 12% of email recipients got 8 or more emails in four weeks, with opt-outs four times the norm, and recommends a cap of 3 a week. The reach stage finds 61% of customers email-reachable and a steady consent trend.

```
- F1 (chosen, high): rate complaint drift; 0.14% recent vs 0.06% baseline; 70% of complaints from recipients with no open in 180 days. Next: scenario-template-launcher
- F2 (done, medium): channel email over cap; 12% over 3 a week; opt-out 4x. Next: contact-frequency-audit
- F3 (open, low): channel sms consent gap; 22% with a phone have no SMS consent. Next: engagement-segment-builder
```

The user sets a 3-a-week cap in Engagement the same day (F2 done). `scenario-template-launcher` finds no sunset flow to clone (`no_source`); `engagement-scenario-builder` builds one from the outline after its yes (C1, create `scenario 6a3c00000000000000000003`). `scenario-qa`: GO. The user switches it on on 6 November.

```
**Next:** recheck with deliverability-trend, not before 2026-12-04.
```

**Session 2 (5 December).** The four weeks since the start pool at 0.07%: **improved**. The cap started the same week, so the summary credits both and can't split them.
