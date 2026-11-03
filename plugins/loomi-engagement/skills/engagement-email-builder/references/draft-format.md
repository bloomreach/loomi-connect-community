# Draft spec

`scripts/email_draft_plan.py plan` reads the draft spec (`--draft`) and the HTML body (`--html`) from your working folder. The spec is one JSON object:

```json
{
  "name": "Black Friday – lapsed VIPs – DRAFT",
  "subject": "Your VIP 20% is waiting, {{ customer['first_name'] | default('there', true) }}",
  "preheader": "Three picks we think you'll love, plus a code that ends Sunday.",
  "sender": {"name": "<sender name>", "email": "<sender address>", "source": "project_default"},
  "audience": {"type": "segment", "segmentation_id": "<segmentation id>", "segment": "Lapsed VIP"},
  "consent_category": "<category id>",
  "postal_address": null,
  "user_supplied_hosts": ["images.brand-site.example"],
  "frequency_policy": null
}
```

| Key | Required | Notes |
|---|---|---|
| `name` | yes | The campaign name. End it with "DRAFT" so it reads as one in lists |
| `subject`, `preheader` | subject yes | The options the user picked. Jinja allowed, with fallbacks. These are plain text, so no `\| e` here (it would show `&amp;`) |
| `sender` | yes | `name` and `email` of a sender existing campaigns already use. `source` is `project_default` (the first sender from the `senders` subcommand) or `user` (one the user named from that list). Any other address blocks the plan |
| `audience` | yes | One of the three shapes below |
| `consent_category` | usually | A category `id` from `get_consent_settings`. Use `"general_consent": true` instead only when the user asks and the project's `general_consent.email` is true. Never both |
| `unsubscribe_list` | legacy only | Needed instead when `get_consent_settings` says `enabled: false` |
| `postal_address` | when no variable | The address text the user gave, exactly as it appears in the HTML. Leave it null when the footer uses an address project variable |
| `user_supplied_hosts` | no | Hosts the user gave or confirmed are theirs: image and stylesheet hosts, and the brand's own site. Links may carry customer data only to these hosts, and links elsewhere are a warning. The Bloomreach media library (`brxcdn.com`) is always allowed |
| `frequency_policy` | no | A policy `id` from `get_frequency_policies`, only if the user asks. Otherwise the project default applies |

## Audience shapes

**An existing segment** (one or more segments of one segmentation, joined with OR):

```json
{"type": "segment", "segmentation_id": "<id>", "segment": "Lapsed VIP"}
{"type": "segment", "segmentation_id": "<id>", "segments": ["Gold", "Platinum"]}
```

Pass the segmentation's saved `search_segmentations` detail with `--segmentations`. The plan writes the atom `{"type": "attribute", "attribute": {"type": "segmentation", "id": "<id>"}, "constraint": {"type": "string", "operator": "equals", "operands": [{"type": "constant", "value": "<segment>"}]}}`, which engagement-segment-builder documents for reusing a segmentation.

**An existing customer filter**:

```json
{"type": "customer_filter", "customer_filter_id": "<id>"}
```

Pass its saved `search_customer_filters` detail with `--customer-filters`. The plan copies its `filters` and `formula` unchanged, as `create_email_campaign`'s description says to.

**Everyone with consent**, only when the user explicitly agrees:

```json
{"type": "everyone", "confirmed": true}
```

## What the plan sends

```json
{"project_id": "<project id>",
 "payload": {"name": "...", "schedule": {"type": "now"},
             "customer_filter": {"filters": [...], "formula": "F0"},
             "consent_category": "<category id>",
             "split": {"type": "off", "variants": [{"design": {"type": "raw", "data": {
                 "sender_name": "...", "sender_email": "...", "subject": "...", "preheader": "...",
                 "jinja_html": "<!DOCTYPE html>..."}}}]}}}
```

- `schedule` is required by the tool. `{"type": "now"}` means "send as soon as it is started". The tool always creates a draft and only a person can start it in the Engagement UI, so nothing sends yet, but whoever starts it must set the send time first or it goes out immediately. The read-back shows `schedule.active: true`; that does not mean it is running.
- `provider` is left out, so the project's default email integration applies.
- Pass `payload` to `create_email_campaign` exactly as the plan has it.
