# Playbook: quarter close

Closes a quarter in one job: lists every change your playbook runs made since the quarter started, measures the live ones nobody has confirmed yet, builds the QBR with a measured "work done and what it earned" section, plans next quarter's campaigns, and ends with the playbooks to run next, in order.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of its stage skills (`change-impact-tracker`, `qbr-report`, `campaign-planner`), all read-only |
| **Other requirements** | The `loomi-platform` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Close Q3 for acme and the Acme US project. Our runs are in ./runs."
- "Build the QBR, and show what each change we shipped this quarter actually earned."
- "What should we run next quarter, based on what worked this one?"

## How it works

| Step | Skill | When |
|---|---|---|
| changes | `handoff.py list --changes --since <quarter start>` over the runs folder | now |
| measure | `change-impact-tracker`, once per unconfirmed live change | now |
| review | `qbr-report`, with the measured work done | now |
| plan | `campaign-planner`, for next quarter | now, when the customer has Engagement |
| next | this playbook: the playbooks to run next, in order | now |

`scripts/handoff.py` keeps this close's hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)) and lists the changes every run made. The plays it picks are recorded as findings whose next skill is a playbook (`playbook_for` in [references/rules.json](references/rules.json)). See [examples/q3-close.md](examples/q3-close.md).

## Notes and limitations

- It measures before it builds the QBR, so the QBR's work done section reports results rather than a to-do list.
- Only changes recorded in hand-off files are measured. Rules changed in the app show in the QBR's work done section, unmeasured; measure one with `change-impact-tracker` on request.
- It reads the other runs' files but never changes them: a run's confirm stage is recorded by its own playbook.
- It works with Discovery, Engagement or both: a run starts with whichever the customer has. Without Engagement, the plan stage is offered for skipping.
- `change-impact-tracker` is observational: a difference-in-differences estimate against a control, not an A/B test.
