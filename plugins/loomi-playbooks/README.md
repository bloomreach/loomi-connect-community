# loomi-playbooks

Playbooks chain existing Loomi Connect skills into one job, from finding a problem to fixing, testing and measuring it. Each skill on its own stops at "hand this to skill X"; a playbook carries the result across for you.

| Skill | What it does | Access |
|---|---|---|
| [playbook-test-and-learn](skills/playbook-test-and-learn/) | Find the Discovery rule costing a query money, A/B test a fix, roll out the winner and confirm it holds, across sessions | **Writes** |

How playbooks work:

- **They don't repeat any skill's logic.** Each stage loads the skill that does it, so install the plugins those skills are in (each playbook's README lists them).
- **A hand-off file links the stages.** It holds the context, the stages, the findings and a change log, in the shape in [docs/hand-off-format.md](../../docs/hand-off-format.md). Tests run for weeks, so the file is also how a playbook picks up again in a later session.
- **Writes stay with the stage skills.** Every write is shown and confirmed in the skill that makes it. A yes to a playbook is never a yes to a write.

To add a playbook or a skill, see [CONTRIBUTING.md](../../CONTRIBUTING.md).
