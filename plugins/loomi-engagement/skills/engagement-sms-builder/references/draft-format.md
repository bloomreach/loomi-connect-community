# Draft spec

`scripts/sms_draft_plan.py plan` reads the draft spec (`--draft`) from your working folder. The spec is one JSON object, and the message lives in it:

```json
{
  "name": "Boots weekend - lapsed VIPs - SMS DRAFT",
  "brand": "Acme Outdoor",
  "message": "Acme Outdoor: Hi {{ customer['first_name'] | default('there', true) }}, 20% off boots ends Sunday. https://go.acme-outdoor.example/boots Reply STOP to opt out, HELP for help",
  "translations": {},
  "sender": {"name": "Acme Outdoor", "sender": "AcmeOutdr", "source": "project_default"},
  "audience": {"type": "segment", "segmentation_id": "<segmentation id>", "segment": "Lapsed VIP"},
  "consent_category": "<category id>",
  "user_supplied_hosts": ["go.acme-outdoor.example"],
  "regions": ["US", "US-TX"],
  "schedule": {"type": "now"},
  "recipient_utc_offsets": [],
  "transactional": false,
  "regulated_industry": false,
  "frequency_policy": null
}
```

| Key | Required | Notes |
|---|---|---|
| `name` | yes | The campaign name. End it with "DRAFT" so it reads as one in lists |
| `brand` | yes | The brand name the message must name in its first `sms_brand_window_chars` characters |
| `message` | yes | The default-language text (saved under the `""` language key). Plain text: Jinja allowed, no HTML, no `\| e` |
| `translations` | no | `{"es": "..."}` for extra languages, each linted like the default. The default always stays under `""` |
| `sender` | yes | `name` (display name) and `sender` (the sender ID: 1–11 letters and digits with at least one letter, or a phone number of 3–17 digits, optionally with `+`). `source` is `project_default` (the `senders` subcommand's default) or `user` (a sender ID the user gave, a warning to confirm it's registered) |
| `audience` | yes | One of the shapes below |
| `consent_category` | usually | A category `id` from `get_consent_settings`. Use `"general_consent": true` instead only when the user asks and `general_consent.sms` is true. Never both |
| `unsubscribe_list` | legacy only | Needed instead when `get_consent_settings` says `enabled: false` |
| `user_supplied_hosts` | when there's a link | Link hosts the user gave or confirmed are theirs: their domain or their own shortener. Subdomains match. Any other host blocks the plan |
| `regions` | recommended | Where recipients can be: `US`, `CA`, and `US-XX` for states the user names. Left empty, every US state plus Canada is assumed (`assumed_regions`) and the plan says so. `US-TX` or `CA` makes the brand check a blocker; `CA` needs a link to the sender's contact details |
| `schedule` | no | `{"type": "now"}` (the default) or `{"type": "datetime", "datetime": <Unix seconds>}`. Event schedules are refused: build a scenario instead |
| `recipient_utc_offsets` | with a datetime | The UTC offset **on that date** (daylight saving included) of every time zone the audience covers, such as `["-05:00", "-06:00", "-07:00", "-08:00"]`. The script never guesses an offset |
| `transactional` | no | `true` only when the user says the text is purely transactional: missing STOP wording becomes a warning |
| `regulated_industry` | no | `true` for finance, healthcare, insurance, alcohol and similar: missing HELP wording becomes a blocker |
| `frequency_policy` | no | A policy `id` from `get_frequency_policies`, only if the user asks |
| `type` | no | `sms` (the default). MMS isn't supported |

For a revision (step 11) also set:

| Key | Notes |
|---|---|
| `campaign_id` | The draft being revised. Must match the `--existing` file |
| `origin` | `created_this_session` (this skill made it in this session; pass the id `create_sms_campaign` returned as `--created-id`, which must match) or `user_named` |
| `user_confirmed` | `true` once the user has confirmed a `user_named` draft by name |

## Audience shapes

```json
{"type": "segment", "segmentation_id": "<id>", "segment": "Lapsed VIP"}
{"type": "segment", "segmentation_id": "<id>", "segments": ["Gold", "Platinum"]}
{"type": "customer_filter", "customer_filter_id": "<id>"}
{"type": "everyone", "confirmed": true}
```

Pass the segmentation's saved `search_segmentations` detail with `--segmentations`, or the filter's `search_customer_filters` detail with `--customer-filters`. A segment becomes an inline segmentation atom; a customer filter's `filters` and `formula` are copied unchanged. The `sms-template-best-practices` guide also shows `{"customer_filter": {"id": ...}}`, but `create_email_campaign`'s description says a saved filter can't be referenced by ID, so this skill always uses the inline form. "Everyone" needs the user's explicit agreement.

## What the plan sends

A create:

```json
{"project_id": "<project id>",
 "payload": {"name": "...", "schedule": {"type": "now"},
             "customer_filter": {"filters": [...], "formula": "F0"},
             "split": {"type": "off"},
             "action": {"consent_category": "<category id>", "general_consent": false,
                        "variants": [{"type": "sms", "translations": {"": {
                            "message": "...", "sender": {"name": "...", "sender": "..."}}}}]}}}
```

- `schedule` is required by the tool. `{"type": "now"}` means "send as soon as it is started": the tool always creates a draft and only a person can start it in the Engagement UI, so nothing sends yet, but whoever starts it sends it at once. `{"type": "datetime"}` sends at that time once started. The read-back shows `schedule.active: true` for a draft; that doesn't mean it is running.
- `sender.sms` is left out, so the tool fills in `{"provider": null}` and the project's provider applies.
- Silent hours and throughput policies appear in campaign details (`silent_hours`, `throughput_policy`, `action.throughput_policy_id`) but aren't in the tool's documented payload, so the plan never sets them.

An update sends `project_id`, `campaign_id` and the campaign object as fetched with `--existing` (minus editor names, `created`, `edited` and `schedule.active`), with only the name, schedule, audience, consent, frequency policy and the planned languages' `message` and `sender.name`/`sender.sender` replaced (provider keys and other languages are kept). Pass `payload` to the tool exactly as the plan has it.
