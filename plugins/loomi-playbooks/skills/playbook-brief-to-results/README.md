# Playbook: brief to results

Takes one Bloomreach Engagement campaign from a brief to a sent and measured send, by running existing skills in order: build the email (or SMS) draft from the brief, QA it, and once you have scheduled it, check the week's sends and any clashes, then read the results and turn them into findings for the next brief. A hand-off file in your working folder carries the changes, the findings and the dates between stages, so you can pick up after the send.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**, through its stage skills only: `engagement-email-builder` creates one email campaign draft; `engagement-sms-builder` creates one SMS campaign draft and can revise that draft. Each write only after its own explicit "yes". The playbook never schedules or sends: you do that in the Engagement UI |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_email_campaign`, `create_sms_campaign`, `update_sms_campaign` |
| **Other requirements** | The `loomi-engagement` plugin. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Here's the brief for the Black Friday VIP email. Build it, check it, and tell me how it did after it goes out."
- "Same, but as a text: 20% off boots this weekend for lapsed VIPs."
- "The VIP email went out last Tuesday. Carry on with the run." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| build-email | `engagement-email-builder` | now, after its confirmation (an SMS run skips it) |
| build-sms | `engagement-sms-builder` | now, after its confirmation (an email run skips it) |
| qa | `campaign-qa` | now; done when you schedule the send |
| preflight | `engagement-send-preflight` | once it's scheduled |
| collisions | `engagement-send-collision-check` | once it's scheduled |
| digest | `engagement-campaign-digest` | `digest_after_days` after the send |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it reads the builder's plan and verify files into the change log, records the send day so the digest waits for it, checks the findings written from the digest, and prints what's next and when. See [examples/vip-email.md](examples/vip-email.md).

## Notes and limitations

- Email and SMS are two stages because a stage's skill is fixed; the run skips the one you don't use.
- The preflight and collision check read the campaign calendar, which leaves drafts out, so they run after you schedule the send. They overlap: the preflight's collision step is light, the collision check is the deep one.
- No A/B test: no skill sets one up in Engagement. The digest compares the campaign with the rest of its week and the week before.
- The email builder never edits its draft: a NO-GO is fixed in the Engagement HTML editor or by building a new draft.
