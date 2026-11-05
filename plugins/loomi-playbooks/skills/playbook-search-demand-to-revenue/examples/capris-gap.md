# Example: "capris" from zero results to a campaign

Illustrative only: the account, project, synonym and campaign IDs and all numbers are made up.

**Session 1 (5 November).** "What are people searching for that we're not selling? Fix it and email the people who searched."

The find stage ranks last week's searches. Two become findings; the user picks the first:

```
- F1 (chosen, high): query file 1 rising and failing; 929 sessions (+77% vs baseline), 0 product views, 100% bounce. Next: discovery-zero-results-triage
- F2 (open, medium): query file 2 rising and selling; 412 sessions (+31% vs baseline), conversion near typical. Next: search-demand-to-campaign
```

The triage finds the catalog calls them "cropped trousers": a synonym fix. `discovery-synonym-fixer` plans a one-way synonym, previews it (GO), creates it switched off and switches it on, each after its own yes, in staging and then production. Its plan and verify files go into the change log:

```
- C1: create synonym 50101 on 2026-11-05 (in place)
- C2: enable synonym 50101 on 2026-11-05 (in place, live)
```

The search now lands on cropped trousers, so the collection stage is skipped. `search-demand-to-campaign` finds a search event in Engagement (tier A): 2,140 searchers in 30 days, 610 reachable by email. The user asks for a "You searched for capris" email; the skill shows the full payload and creates draft 8801 after the yes:

```
- C3: create campaign 8801 on 2026-11-05 (unverified)

**Next:** digest with engagement-campaign-digest, not before 2026-11-19.
```

The user plans to send it on 12 November, so the digest is due on the 19th and the measure stage on 26 November.

**Session 2 (20 November).** "Carry on with the capris run." The digest shows the email delivered to 598 people with a 41% open rate, 6.2% click rate and 14 orders.

**Session 3 (27 November).** `change-impact-tracker` measures synonym 50101 on "capris" and its variants against the site-wide search trend: **worked**, revenue per visit up, with its range. The run is finished.
