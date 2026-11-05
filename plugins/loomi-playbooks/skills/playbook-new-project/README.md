# Playbook: new project (first 30 days)

Takes a new Bloomreach customer from "what have we got?" to a plan for the first month. It gets oriented in the Engagement project, runs the go-live checklist, checks Engagement tracking, the Discovery pixel and feeds, the Discovery catalog configuration and the lifecycle flows, and ends with a 30-day plan that names the playbooks to run, in order. Stages for a product the customer doesn't have are passed over.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | Those of its stage skills (`loomi-project-overview`, `implementation-readiness`, `engagement-tracking-health`, `data-feed-health`, `discovery-catalog-config-audit`, `lifecycle-coverage-map`), all read-only |
| **Other requirements** | The `loomi-platform`, `loomi-engagement` and `loomi-discovery` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "We've just started with acme (production) and the Acme US project. What do we fix first, and what's the plan for the first month?"
- "Onboarding plan for a new customer: they go live on 1 December."
- "Carry on with the new project run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| overview | `loomi-project-overview` | now (Engagement) |
| readiness | `implementation-readiness` | now |
| tracking | `engagement-tracking-health` | now (Engagement) |
| feeds | `data-feed-health` | now |
| catalog-config | `discovery-catalog-config-audit` | now (Discovery) |
| lifecycle | `lifecycle-coverage-map` | now (Engagement) |
| plan | this playbook: 30 days, data first, naming the playbooks | at the end |

The overview runs before the checklist because the checklist needs the project's own event names. `scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): each stage's RED and high items and the plan's items are recorded as findings, so the plan can be built in a later session. See [examples/first-month.md](examples/first-month.md).

## Notes and limitations

- It works with Discovery, Engagement or both: a run starts with whichever the customer has, and each stage for a product it doesn't have is offered for skipping.
- `implementation-readiness` already rates the launch rows of tracking and feeds; the tracking and feeds stages add the detail behind them, so some rows appear twice. The plan counts each fix once.
- Configuration fixes are made in the Bloomreach app by the owner the stage names. The playbook changes nothing.
