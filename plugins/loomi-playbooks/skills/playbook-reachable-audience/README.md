# Playbook: reachable audience

Takes one Bloomreach Engagement project from "how many customers can we actually contact?" to "a tested capture form is live, and here is how much reach grew". Five existing skills run in order: measure reach and consent by channel, check whether a capture form already runs on site, write the form's weblayer code, QA it before launch, and once you have launched it as an A/B test, read the result and re-run the reach audit. A hand-off file in your working folder carries the findings, the launch and the dates, so you can pick up in a later session.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only. You paste the code, set the split and launch the form in the Engagement UI; the playbook records the launch |
| **Loomi Connect tools** | Those of its stage skills (read tools only) |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "We can only email a third of our customers. Grow that."
- "Do we have a newsletter sign-up on site, and is it any good? Build a better one and test it."
- "Carry on with the reachable-audience run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| reach | `contactability-audit` | now |
| on-site | `onsite-experience-audit` | now |
| build | `engagement-weblayer-builder` | now |
| qa | `engagement-weblayer-qa` | now; done when you launch the form |
| read-out | `engagement-experiment-readout` | `min_test_days` after the launch |
| recheck | `contactability-audit` | `recheck_after_days` after the launch |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it checks the findings written from the reach audit, records the launch you made in the app as a change, and prints what's next and when. See [examples/email-signup.md](examples/email-signup.md).

## Notes and limitations

- `engagement-weblayer-builder` doesn't write to Bloomreach: it returns code you paste into the weblayer editor. So the whole playbook is read-only, and the launch is recorded as a change with source `engagement-ui`.
- The test compares two versions of the form on sign-ups (the `banner` event's `subscribe` action). A Control group can't sign anyone up, so on its own it only tells you whether the form costs purchases.
- A capture form grows reach among visitors. People who already gave an address but no consent need a re-permission message: build the audience with `engagement-segment-builder` outside this run; a scenario A/B test can be set up with engagement-ab-test-setup for that message.
- The recheck is a before-and-after comparison of the reach audit: other campaigns and checkout changes move consent too.
