# Example: a monthly client portfolio run

Illustrative only: the organisation, project IDs, file names and all numbers are made up.

**Session 1 (5 November).** "Which client projects need us this month? Runs are in ./clients, one folder per project."

The overview scores 18 projects: 11 green, 4 amber, 3 red (outcome `projects_flagged`). The user agrees to deeper mode on the 7 lowest (21 calls): one project has had no events for 7 days, and two have no live scenarios (`checked`).

Step 3 lists each flagged project's folder:

```
| Run | Playbook | Subject | Progress | Next | Due |
|---|---|---|---|---|---|
| run2.handoff.json | lifecycle-gap | project | 3/7 stages | qa (scenario-qa) | now |
```

That is project 7a10c2: it already has a lifecycle-gap run waiting at QA, so the pick is to resume it. The picks:

```
- F1 (chosen, high): project 5e8c41 no recent events; score 35 red; no events in 7 days. Next: engagement-tracking-health
- F2 (chosen, high): project 7a10c2 no live scenarios; score 58 amber; lifecycle-gap run open at qa. Next: playbook-lifecycle-gap
- F3 (chosen, medium): project 91bd03 no campaign events; score 62 amber; 4100 customers. Next: playbook-new-project
- F4 (open, medium): project 33f0e8 no live scenarios; score 70 amber. Next: playbook-lifecycle-gap
```

The team takes on F1 to F3 now, each in its own project folder; F4 waits for the next portfolio run. The portfolio run itself changes nothing.
