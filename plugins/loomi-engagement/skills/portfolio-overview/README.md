# Portfolio overview

Builds one health table across every Bloomreach Engagement project in an organisation, for agencies, partners and multi-brand teams. A single `list_projects_with_overview` call gives each project's customers, events and event types; the skill adds a light health score and flags empty projects, very small or shrinking customer bases, projects that have never sent a campaign, test or sandbox-looking projects and outliers against the portfolio median. An optional deeper mode checks, for a capped number of projects, whether events arrived in the last 7 days and whether any scenarios are live, after telling you how many calls that takes. Each flagged project is handed to the skill that looks into it. It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects_with_overview`; in deeper mode `estimate_eql_cost`, `execute_analytics_eql`, `search_scenarios` |
| **Other requirements** | None. Python 3 is optional, for the bundled script (standard library only) |
| **Tested with** | Claude Code, read-only, against a demo organisation: `list_cloud_organizations`, `list_projects_with_overview`, `get_project_overview` (to confirm it returns the same snapshot), and for one project `estimate_eql_cost`, `execute_analytics_eql` and `search_scenarios` with `status="active"`, to confirm the response shapes. The script was tested on synthetic responses. Not run end to end as one session, and not tested in an OpenAI client. |
| **Maintainer** | Bloomreach |

## Example prompts

- "Give me a health overview of all our client projects in Bloomreach."
- "Which of our brands' Engagement projects need attention?"
- "Has tracking stopped in any of our projects? Check the five worst."
- "Compare this month's portfolio with the last run."

See [examples/illustrative-portfolio.md](examples/illustrative-portfolio.md) for an example output. Every name and number in it is fictional.

## How it works

1. Resolves the organisation (asking if there's more than one) and calls `list_projects_with_overview` once.
2. [scripts/portfolio_health.py](scripts/portfolio_health.py) scores each project from the overview, using the rules in [references/rules.json](references/rules.json) and [references/health-checks.md](references/health-checks.md), and compares it with the median of comparable projects. With `--baseline` it compares customer counts with an earlier run.
3. Offers deeper mode for the lowest-scoring projects, capped and with the call count stated first: one aggregate EQL count of the last 7 days' events by type, and one active-scenario list per project.
4. Returns the table, the projects that need attention with the skill to run next (each flag's `handoff` in [references/rules.json](references/rules.json)), and what wasn't checked.

## Notes and limitations

- The overview has no last-event date and no campaign or scenario counts, so "tracking stopped" and "no live scenarios" need deeper mode. Without it, the all-time `campaign` event count shows only whether a project has ever sent anything.
- Shrinking customer bases need a baseline: keep the script's `--out` file and pass it next time.
- Test and sandbox detection uses the project category and words in the name or URL slug, so demo projects are flagged too.
- Outliers compare projects of different sizes and industries; treat them as pointers, not verdicts.
- The output names only projects, workspaces and counts. It never lists users, editors or other organisations.
