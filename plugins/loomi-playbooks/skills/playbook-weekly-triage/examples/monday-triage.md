# Example: a Monday triage

Illustrative only: the account, project, IDs, file names and all numbers are made up.

**Monday 9 November.** "It's Monday. What's due this week? Our runs are in ./runs."

Step 0 lists the folder with `--today` set to Sunday 15 November:

```
| Run | Playbook | Subject | Progress | Next | Due |
|---|---|---|---|---|---|
| run1.handoff.json | test-and-learn | query | 2/5 stages | read-out (discovery-experiment-readout) | now |
| run2.handoff.json | test-and-learn | category | 4/5 stages | confirm (change-impact-tracker) | from 2026-11-12 |
| run3.handoff.json | test-and-learn | query | 1/5 stages | test (discovery-experiment-setup), can be skipped | now |
| run4.handoff.json | test-and-learn | query | 5/5 stages | finished | |
```

So: one read-out due now, one confirm due Thursday, and run3 can be skipped (its `skip_reason`: the find stage found nothing worth testing).

The briefing shows revenue down 6.1% on the week, and its three things include "find out why", so the outcome is `big_change`. The explain stage finds that most of the drop is the search channel on mobile from Wednesday, and the conversion pixel's issue rate rose the same day: `data_problem`.

The picks:

```
- F1 (open, high): pixel conversion-pageview data problem; issue rate 34% from 2026-11-04. Next: data-feed-health
- F2 (open, high): query file 1 low conversion; conversion 9.8% vs 18.0% typical; up to 14k this week. Next: playbook-test-and-learn
- F3 (open, medium): flow 12 stopped; cart abandonment scenario inactive since 2026-11-02. Next: playbook-lifecycle-gap
```

F1 comes first because the other numbers can't be trusted until the pixel is fixed; no playbook covers it, so it names the skill. The user picks F2 and runs `playbook-test-and-learn` for that query, which starts its own hand-off file. The triage itself changes nothing.
