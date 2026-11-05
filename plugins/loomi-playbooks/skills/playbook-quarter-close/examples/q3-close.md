# Example: closing Q3

Illustrative only: the account, project, IDs, file names and all numbers are made up.

**Monday 5 October.** "Close Q3 for acme and the Acme US project. Our runs are in ./runs."

Step 0 lists the changes from 1 July to 30 September (`--since` and `--until`), with whether each is live, and shows each run with live changes read-only for its confirm verdict:

```
| Change | Run | Live from | Live? | Confirmed |
|---|---|---|---|---|
| end experiment 777 (variant kept, rule 900101) | run1.handoff.json | 2026-07-20 | live | worked (confirm stage, 2026-08-04) |
| update rule 900233 | run2.handoff.json | 2026-08-28 | live | not confirmed |
| create rule 900310 (disabled) | run4.handoff.json | 2026-09-02 | not live | not shipped |
| enable rule 900412 | run5.handoff.json | 2026-09-24 | live | too early (11 days), measure from 2026-10-08 |
```

The measure stage runs `change-impact-tracker` once, for rule 900233: **no clear effect**, revenue per visit −2% to +6%. Outcome `some_too_early`, because rule 900412 waits until 8 October.

The review stage builds the QBR. Its work done section now reads:

```
| Change | Run | Live from | Verdict | Effect (95% range) | Revenue / month |
|---|---|---|---|---|---|
| rule 900101 (won A/B test) | run1 | 2026-07-20 | worked | RPV +4.1% (+1.2% to +7.0%) | about 6,200 (1,800 to 10,600) |
| rule 900233 | run2 | 2026-08-28 | no clear effect | RPV +2% (−2% to +6%) | — |
| rule 900412 | run5 | 2026-09-24 | too early, measure from 2026-10-08 | — | — |
```

The plan stage gives `campaign-planner` next quarter, from 1 October; Black Friday and Christmas lead the plan.

Next quarter's playbooks, in order: `playbook-test-and-learn` on the rule 900233 query (no clear effect, worth a clean test), `playbook-findability` on the dead-end searches the QBR ranked first, and `playbook-lifecycle-gap` for the missing win-back flow. The close itself changes nothing.
