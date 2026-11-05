# Playbook: weekly triage

The Monday "what do we work on this week?" in one pass. It lists every playbook run in your folder of hand-off files, so you see which read-outs, confirms and re-checks fall due this week and which runs can be skipped; builds the weekly briefing; explains a big revenue change when there is one; and picks up to three problems, naming the playbook that starts or resumes for each. It starts nothing that writes: it hands off.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of its stage skills (`weekly-ecommerce-briefing`, `revenue-anomaly-explainer`), all read-only |
| **Other requirements** | The `loomi-platform` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "It's Monday. What's due this week, and what should we work on?"
- "Run the weekly triage for acme, production, and the Acme US project. Our runs are in ./runs."
- "Which of our tests and changes need a check this week?"

## How it works

| Step | Skill | When |
|---|---|---|
| runs | `handoff.py list` over the runs folder | now |
| briefing | `weekly-ecommerce-briefing` | now |
| explain | `revenue-anomaly-explainer` | now, only when the briefing shows a big change |
| pick | this playbook, from the briefing, the explanation and the runs | now |

`scripts/handoff.py` keeps this week's hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)) and lists the other runs with what's next and when. The problems it picks are recorded as findings whose next skill is a playbook (`playbook_for` in [references/rules.json](references/rules.json)). See [examples/monday-triage.md](examples/monday-triage.md).

## Notes and limitations

- It never continues another run: it says which are due, and that run's own playbook does the stage.
- It works with Discovery, Engagement or both: a run starts with whichever the customer has, and the explain stage is offered for skipping without Discovery.
- `revenue-anomaly-explainer` covers Discovery. A change in Engagement purchases is handed to `engagement-revenue-change-explainer`.
- The playbooks it names are separate skills. When one isn't installed, it names the stage skill the briefing linked instead.
