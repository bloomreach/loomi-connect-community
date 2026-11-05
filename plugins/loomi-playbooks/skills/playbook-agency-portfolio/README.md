# Playbook: agency portfolio

For agencies, partners and multi-brand teams with many Engagement projects. It scores every project in the organisation from one call, checks recent events and live scenarios on the weakest ones, looks at the runs each project already has, and names the playbook to start or resume for up to a set number of flagged projects. It starts nothing: each project's playbook runs on its own, in its own hand-off file.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of `portfolio-overview`, all read-only |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand. Each client project's runs kept in a folder of their own |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Which of our client projects need attention this month, and what should we run on each?"
- "Run the portfolio review for our agency organisation. Our runs are in ./clients, one folder per project."
- "Carry on with the portfolio run: the deeper check is fine to run on 8 projects." (with its hand-off file)

## How it works

| Step | Skill | When |
|---|---|---|
| overview | `portfolio-overview` | now |
| deeper | `portfolio-overview` (deeper mode) | now, after a yes to the call count, unless every project is green |
| runs | `handoff.py list` over each flagged project's runs folder | now |
| pick | this playbook, from the flags and the runs | now |

`scripts/handoff.py` keeps this portfolio run's hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)) and lists each project's runs with what's next and when. The projects picked are recorded as findings whose next skill is a playbook (`playbook_for` in [references/rules.json](references/rules.json)), capped at `max_chosen`. See [examples/client-portfolio.md](examples/client-portfolio.md).

## Notes and limitations

- The playbooks it names (`playbook-new-project`, `playbook-lifecycle-gap`, `playbook-revenue-drop`, `playbook-weekly-triage`) are separate skills, each run for one project in its own hand-off file. Where no playbook fits (tracking that stopped, an unreadable overview), it names a single skill.
- `handoff.py list` shows a run's playbook, subject and next stage, but not its project. Runs started with `--subject-kind project` show the project ID; for the rest, keep each project's runs in a folder of their own.
- The hand-off script needs a project ID for an Engagement run, so the portfolio run is started with one project of the organisation; its subject is the organisation, and it covers every project.
- The overview has no revenue, campaign count or last-event date. A revenue drop is picked only when a client reports one, and recent activity is known only for projects deeper mode checked.
