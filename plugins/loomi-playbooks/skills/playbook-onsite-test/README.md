# Playbook: on-site test

Takes one Bloomreach Engagement project from "what should we test on site?" to "the test has run, and here is the winner", with the A/B test Marketing can run today: a weblayer's own split. Four existing skills run in order: find the weblayer worth testing, write the challenger's code, QA it before launch, and once you have launched the test in the Engagement app, read the result when it has run long enough. A hand-off file in your working folder carries the findings, the launch and the dates, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only. You paste the code, set the split and launch the test in the Engagement UI; the playbook records the launch |
| **Loomi Connect tools** | Those of its stage skills (read tools only) |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "What should we A/B test on site? Set one up."
- "Test a shorter headline on our newsletter pop-up."
- "Our pop-up test has been running two weeks. Did the new version win?" (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| find | `onsite-experience-audit` | now |
| build | `engagement-weblayer-builder` | now |
| qa | `engagement-weblayer-qa` | now; done when you launch the test |
| read-out | `engagement-experiment-readout` | `min_test_days` after the launch, or the planned end date |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the audit, records the launch you made in the app as a change, and prints what's next and when. See [examples/popup-headline.md](examples/popup-headline.md).

## Notes and limitations

- `engagement-weblayer-builder` doesn't write to Bloomreach: it returns code you paste into the weblayer editor. So the whole playbook is read-only, and the launch is recorded as a change with source `engagement-ui`.
- The test is the weblayer's own A/B split: the original against the challenger, or the challenger against a Control group. `engagement-experiment-readout` reads weblayer splits from `banner` events when asked, and web experiments too, if your team runs on-site tests there.
- Paste into an inactive copy, never the live weblayer: a variant added to an active weblayer is live when saved.
- For a test of a message in a flow rather than an on-site experience, a scenario A/B test can be set up with engagement-ab-test-setup.
