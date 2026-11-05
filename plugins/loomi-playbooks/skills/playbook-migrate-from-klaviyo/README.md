# Playbook: migrate from Klaviyo

Takes one Bloomreach Engagement project from "we're leaving Klaviyo" to "the emails are here, checked, and the first missing flow is rebuilt and ready to switch on", by running existing skills in order: convert the Klaviyo email exports into Visual Builder emails in draft scenarios, write the Jinja the conversion left for attention, QA every migrated email, map which lifecycle flows the old account ran that are missing here, clone a proven flow or build on the migrated drafts, and QA the flow before you switch it on. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so a migration can span several sessions.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `convert-klaviyo-email-to-bloomreach` uploads images to the media library and creates one draft scenario per email (and a raw-HTML email campaign only if you ask); `scenario-template-launcher` clones one scenario as a draft that never starts; `engagement-scenario-builder` creates or changes a draft scenario. Each write only after its own explicit "yes". The playbook never switches a flow on: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `import_media_file`, `create_scenario`, `update_scenario_node`, `create_email_campaign`, `clone_scenario`, `update_scenario` |
| **Other requirements** | The `loomi-engagement` plugin. The convert stage needs Python 3 with `beautifulsoup4` and `jinja2` in a virtual environment in your working folder (the converter sets it up). Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "We're moving this client off Klaviyo. Here are their email exports: migrate them and rebuild the flows."
- "Which of our Klaviyo flows don't exist in Bloomreach yet? Rebuild the biggest one."
- "Carry on with the Klaviyo migration run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| convert | `convert-klaviyo-email-to-bloomreach` | now, after its write plan's confirmation |
| jinja | `engagement-jinja-writer` | now |
| qa-emails | `scenario-qa` | now |
| coverage | `lifecycle-coverage-map` | now |
| launch | `scenario-template-launcher` | now, after its confirmation |
| adapt | `engagement-scenario-builder` | now, after confirmations |
| qa-flow | `scenario-qa` | now; done when you switch the flow on |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records the converter's and the builder's writes, reads the launcher's plan and verify files into the change log, checks the findings written from the coverage map, records the day the flow started, and prints what's next. See [examples/client-migration.md](examples/client-migration.md).

## Notes and limitations

- The email QA uses `scenario-qa`, not `campaign-qa`: the converter pushes each email as a draft scenario. `campaign-qa` is for a raw-HTML email campaign, which the converter makes only when you ask.
- An adapt stage sits between launch and the flow QA: a migrated flow email is one trigger and one email, with no wait or did-not-purchase condition, and the launcher never edits its clone.
- Jinja from `engagement-jinja-writer` goes into the Visual Builder: the Visual Builder design is the email, so Jinja pasted only into the HTML is lost on the next save.
- One flow is rebuilt per run. For the next one, and to measure a rebuilt flow once it's live, run `playbook-lifecycle-gap`. A scenario A/B test can be set up with engagement-ab-test-setup to compare a rebuilt flow's timing with the old one.
