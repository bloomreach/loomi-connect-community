# Engagement SMS builder

Turns a short brief ("a text for lapsed VIPs, 20% off boots this weekend") into a Bloomreach Engagement SMS campaign **draft**: three message options with personalization written to engagement-jinja-writer's rules, the brand name up front, STOP and HELP wording, a link on the user's own domain or shortener, an existing sender, an audience chosen from existing segments or customer filters, and an SMS consent category. It lints the text (GSM-7 or Unicode, segment count, compliance, links, Jinja, placeholders), checks a send time against US quiet hours and state windows, shows exactly what will be created, creates it only after an explicit yes, reads it back, and hands it to `campaign-qa`. It can also revise a draft it made, or one you name and confirm, while it is still a draft.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: creates one SMS campaign draft (`create_sms_campaign`) and can revise one draft (`update_sms_campaign`: one it created in the session, or one you name and confirm, and only while its status is `draft`), each after you confirm. Never starts, schedules a time inside quiet hours, sends or deletes (`delete_sms_campaign` is never called) |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_guide`, `get_consent_settings`*, `get_customer_property_schema`, `search_voucher_pools`*, `search_segmentations`, `search_customer_filters`, `search_sms_campaigns`, `get_frequency_policies`*; writes: `create_sms_campaign`, `update_sms_campaign`* (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | Python 3 for `scripts/sms_draft_plan.py` (standard library only) |
| **Tested with** | Claude Code: the payload follows `create_sms_campaign`'s and `update_sms_campaign`'s schemas and the `sms-template-best-practices` guide, and the campaign detail, consent and not-found shapes were checked read-only against a demo project. The script was tested on synthetic data. No live create or update was run while building the skill. Not yet tested in an OpenAI client |
| **Maintainer** | @bloomreach |

## Example prompts

- "Write a text for our lapsed VIPs: 20% off boots this weekend, link to go.acme-outdoor.example/boots."
- "Draft an SMS for the 'Running fans' segment about the new trail shoe, to go out Saturday at 11am Eastern."
- "Shorten the SMS draft you just made so it fits in one segment."

See [examples/boots-weekend-lapsed-vips.md](examples/boots-weekend-lapsed-vips.md) for illustrative output.

## How it works

1. **Brief:** pins down the offer, link and its host, brand, audience, where recipients are and the send time, asking once for anything missing.
2. **Look-ups (read-only):** consent settings, property names, a voucher pool, matching segments, and the sender existing SMS campaigns use.
3. **Options:** three messages with their encoding and segment count; you pick one.
4. **Lint and plan:** `sms_draft_plan.py plan` blocks the draft on missing STOP wording, a missing brand (Texas and Canada), more than the segment limit, a non-https link, a link host you didn't supply, customer data in a link, a backslash, `@` or Jinja in a link's host, Canada without contact details, banned or unbalanced Jinja, leftover placeholders, missing consent, an unknown sender, and a send time inside quiet hours.
5. **Confirm, write, verify:** shows the full message and what the schedule means, waits for a yes, writes once, reads it back with `sms_draft_plan.py verify`, and hands it to `campaign-qa`.

## Notes and limitations

- **Schedule.** The tool requires a schedule. `{"type": "now"}` sets no time: the draft sends the moment someone starts it in the Engagement UI. A fixed time is checked against the federal window and the state windows in [references/rules.json](references/rules.json) for each recipient UTC offset you give.
- **Silent hours.** Loomi Connect can't set silent hours or throughput policies on an SMS campaign. Set them in the Engagement UI before starting the draft; campaign-qa reports their absence as a blocker.
- **Compliance.** The checks reuse campaign-qa's and scenario-qa's SMS rules (STOP, brand, HELP, CASL, quiet hours, state windows, Texas SB 140). They flag risk for a person to judge; they aren't legal advice, and carrier approval is outside the skill's control.
- **Sender.** The default is the newest sender existing SMS campaigns use whose name doesn't look like a placeholder. In a project with no SMS campaigns, you give the sender ID registered with your provider.
- **Single message only.** No A/B splits and no MMS. A revision is refused for a campaign with a split or MMS.
- **Plan file.** The plan uses the shared plan-file shape (docs/skill-authoring.md) with `project_id` and `project_name`. A create's `undo` is empty because the skill never deletes; a revision's `undo` puts back the draft as it was fetched.
