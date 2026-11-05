# Playbook: voice of customer

Takes one Bloomreach Engagement survey from "what are customers telling us?" to "the unhappy ones were followed up, and here is whether the score moved", by running existing skills in order: read the survey's scores and answers with how far to trust them, build the follow-up audience (for example detractors) from aggregate answers, follow them up with a draft flow triggered by the answer (optionally with an A/B split, such as a holdout) or a one-off email draft, QA it, and once it is live, read the flow's test out and read the survey again. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `engagement-segment-builder` creates one customer filter or segmentation; `engagement-scenario-builder` creates or changes a draft scenario; `engagement-ab-test-setup`, if you want a test, adds an A/B split to the draft flow (or, for a running flow, makes a new draft copy with it); `engagement-email-builder` creates one email campaign draft. Each write only after its own explicit "yes". The playbook never switches a flow on or sends: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_customer_filter`, `create_segmentation`, `create_scenario`, `update_scenario`, `update_scenario_node`, `create_email_campaign` |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our NPS survey has more detractors than promoters. Follow them up and tell me if it helps."
- "Set up a follow-up for anyone who gives us one or two stars."
- "Carry on with the voice-of-customer run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| listen | `engagement-survey-insights` | now |
| segment | `engagement-segment-builder` | now, after its confirmation |
| flow | `engagement-scenario-builder` | now, after its confirmation (the flow path) |
| test | `engagement-ab-test-setup` | now, after its confirmation (the flow path, optional) |
| qa-flow | `scenario-qa` | now; done when you switch the flow on |
| email | `engagement-email-builder` | now, after its confirmation (the email path) |
| qa-email | `campaign-qa` | now; done when you schedule the send |
| ab-read-out | `engagement-experiment-readout` | `readout_after_days` after the flow started (skipped without a test) |
| recheck | `engagement-survey-insights` | `recheck_after_days` after the follow-up went live |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the survey read-out, records the segment and flow writes, reads the A/B test setup's and the email builder's plan and verify files into the change log, records the day the follow-up went live, and prints what's next and when. See [examples/nps-detractors.md](examples/nps-detractors.md).

## Notes and limitations

- The follow-up is a flow or an email, not both: the flow stage's outcome picks the path, and `status` offers the other path's stages as skips.
- The flow is built by `engagement-scenario-builder` rather than cloned by `scenario-template-launcher`: a survey follow-up isn't one of the lifecycle flows the launcher clones. The builder doesn't write message content: it leaves a label where the message goes, for you to add in Engagement or copy from an existing scenario.
- Answers are counted, never listed, and the audience is defined by answer values only, never by free text.
- The recheck reads the survey before and after, and later respondents are mostly different people. On the flow path, the optional test stage can add a holdout with `engagement-ab-test-setup` to compare following up against not following up; `engagement-experiment-readout` reads it out. Skip the test stage and `status` offers the ab-read-out stage as a skip.
