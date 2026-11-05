# Example: following up NPS detractors

Illustrative only: the project, survey, segment and scenario IDs and all numbers are made up.

**Session 1 (5 November).** "Our NPS survey has more detractors than promoters. Follow them up and tell me if it helps."

`engagement-survey-insights` reads the post-delivery survey over 90 days: 640 respondents, NPS-style score −8 (1 to 10 stars, interval −15 to −1). One finding:

```
- F1 (chosen, high): survey 6a4d00000000000000000001 question 1 detractors outnumber promoters; 38% detractors of 640 answers. Next: engagement-segment-builder
```

`engagement-segment-builder` maps "answered question 1 with 1 to 6 stars in the last 90 days, with email consent and an email address" to the `survey` event and the newsletter consent category, sizes it at about 220 customers, and after its yes creates it:

```
- C1: create customer filter 6a4d00000000000000000002 on 2026-11-05 (unverified)
```

The user wants every future detractor followed up, so the flow path: `engagement-scenario-builder` outlines a flow triggered by the `survey` event with the low-score condition, a one-day wait, and a label where the "sorry, here's how we'll fix it" email goes. After its yes it creates the draft (C2). The user adds the email in Engagement. The user doesn't want an A/B test this time, so the test stage is skipped; later, `status` offers the ab-read-out stage as a skip. `scenario-qa` returns GO. The user switches it on on 6 November:

```
- C3: start scenario 6a4d00000000000000000003 on 2026-11-06 (in place, live)
**Next:** email with engagement-email-builder (suggested skip: a follow-up flow was built instead of an email).
```

The user skips the email stages. The recheck counts from the qa-flow stage's start date, so it's due on 5 January.

**Session 2 (6 January).** The recheck: 410 respondents since 6 November, score +2 (interval −7 to +11). The intervals overlap with the first reading: **no clear change**. The user decides to keep the flow and look at the delivery step the answers point to with `funnel-leak-finder`.
