# Engagement email builder

Turns a short brief ("a Black Friday email for lapsed VIPs, 3 product picks, 20% code") into a Bloomreach Engagement email campaign **draft**: three subject lines and preheaders to choose from, a responsive HTML email with personalization, a recommendations block and an offer block written to engagement-jinja-writer's rules, the unsubscribe link and postal address, the project's existing sender, and an audience chosen from existing segments or customer filters. It lints the email, shows exactly what will be created, creates it only after an explicit yes, reads it back to check it, and hands it to `campaign-qa`.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: creates one email campaign draft (`create_email_campaign`), after you confirm. Never schedules, starts or sends it, and never edits or deletes existing campaigns |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_guide`, `get_consent_settings`*, `list_project_variables`, `get_customer_property_schema`, `search_recommendations`, `search_catalogs`, `search_voucher_pools`*, `search_segmentations`, `search_customer_filters`, `search_email_campaigns`, `get_frequency_policies`*; write: `create_email_campaign` (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | Python 3 for `scripts/email_draft_plan.py` (standard library only) |
| **Tested with** | Claude Code: the payload follows `create_email_campaign`'s schema and the `email-template-best-practices` guide, and the read-back and sender shapes were checked read-only against a demo project. The script was tested on synthetic data. No live create was run while building the skill. Not yet tested in an OpenAI client |
| **Maintainer** | @bloomreach |

## Example prompts

- "Build a Black Friday email for our lapsed VIPs: three product picks and a 20% code."
- "Draft a back-in-stock newsletter for people in the 'Running fans' segment."
- "Write a spring launch email for Gold and Platinum members and save it as a draft."

See [examples/black-friday-lapsed-vips.md](examples/black-friday-lapsed-vips.md) for illustrative output.

## How it works

1. **Brief:** pins down the offer, code, products, landing URLs and audience, asking once for anything missing. It never invents an offer, a code or a URL.
2. **Look-ups (read-only):** consent settings, the postal address variable, property names, the recommendation engine and its catalog, a voucher pool, matching segments, and the sender existing campaigns use.
3. **Build:** subject and preheader options, then the HTML from [assets/starter-email.html](assets/starter-email.html) and a draft spec.
4. **Lint and plan:** `email_draft_plan.py plan` blocks the draft on a missing unsubscribe link or postal address, unbalanced Jinja, `<script>`, images or tracking pixels from hosts you didn't supply, missing alt text, an over-long subject or leftover placeholder text, and on an unknown sender, a missing segment or a consent mismatch.
5. **Confirm, create, verify:** shows the full draft and waits for a yes, creates it once, reads it back with `email_draft_plan.py verify`, and hands it to `campaign-qa`.

## Notes and limitations

- **Raw HTML only.** Loomi Connect's `create_email_campaign` takes `design.type: "raw"`; it can't create a Visual Builder design, so the draft opens in the HTML editor.
- **Schedule.** The tool requires a schedule, so the draft is created with `{"type": "now"}`, which sets no send time. Whoever starts it in the Engagement UI sets the time first.
- **Sender.** The project default is the sender of the most recently edited campaign; Loomi Connect has no "default sender" setting to read. A sender you name must already be used by an existing campaign.
- **Audience.** Existing segments and customer filters only. Building a new audience is `engagement-segment-builder`'s job.
- **Images.** Images must be on the Bloomreach media library or a host you supply. The skill doesn't upload images.
- **Plan file.** The plan uses the shared plan-file shape (docs/skill-authoring.md) with `project_id` and `project_name` in place of Discovery's `account` and `environment`. Its `undo` is empty because the skill never deletes; delete an unwanted draft in the Engagement UI.
