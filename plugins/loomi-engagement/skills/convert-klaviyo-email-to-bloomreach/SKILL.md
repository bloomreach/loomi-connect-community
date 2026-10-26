---
name: convert-klaviyo-email-to-bloomreach
description: Migrates Klaviyo email templates (HTML exports) into Bloomreach Engagement — translates Klaviyo template tags to Bloomreach Jinja against the target project's real data, rebuilds the layout as an editable Visual Builder (BEE) email, rehosts images, and pushes each email as a draft scenario via Loomi Connect. Use when someone has Klaviyo email HTML (campaign or flow emails) to move to Bloomreach, mentions migrating from Klaviyo, or pastes HTML containing Klaviyo tags like {{ person.first_name }}, {% unsubscribe %} or {% catalog %}.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement) and Python 3 with beautifulsoup4 and jinja2 (installed with pip into a virtual environment in step 0; needs a client that can install packages).
metadata:
  author: jeffbird13-bloomreach
  version: "1.0.0"
  products: engagement
  access: writes
---

# Klaviyo email → Bloomreach Engagement

Built for agencies and partners migrating clients off Klaviyo. The goal is a **faithful 1:1
migration**: the email in Bloomreach should look and behave like it did in Klaviyo. Do not add
personalization, recommendations or redesigns unless the user asks — offer them at the end.

## Safety

This skill **writes** to Bloomreach Engagement. It can:

- **upload images** to the project's media library (`import_media_file`), one per image rehosted from Klaviyo's CDN;
- **create draft scenarios** (`create_scenario`), one per migrated email, each with one trigger and one email node;
- **fix a node in a scenario it created in this run** (`update_scenario_node`), only when a push needs a correction.

It never activates, starts, sends or test-sends anything, never deletes anything, never edits objects it didn't create in this
run, and never changes project settings, consent, catalogs or customer data.

**Before the first write, show the user exactly what will be created and wait for an explicit "yes"** (step 4b).
If the plan changes afterwards (more images, extra emails, a different project), show the new plan and ask again.

```
0. Setup                                  scripts/... setup → venv + pip install
1. Collect inputs + confirm project      (ask; never assume)
2. Analyze the Klaviyo export(s)          scripts/klaviyo_to_bloomreach.py analyze
3. Audit the Bloomreach project           Loomi Connect reads → mapping.json
4. Confirm the mapping with the user      (one table, once per client)
4b. Confirm the write plan                 (list every image upload + draft scenario; wait for "yes")
5. Rehost images                          import_media_file → mapping.image_map
6. Build + validate                       scripts/... build  +  render-check
7. Push as draft scenario + verify        create_scenario → search_scenario_nodes
8. Migration report                       per email: done / needs attention
```

Read before starting:
- `references/klaviyo-syntax.md` — every Klaviyo tag/block and its Bloomreach equivalent
- `references/loomi-connect.md` — current tool names, rate limits, push/preview gotchas
- `references/bloomreach-jinja.md` — validated Bloomreach Jinja syntax (with doc sources)
- `references/bee-schema.md` — only needed if a push or the Visual Builder reports an error

## 0. Setup

The script needs `beautifulsoup4` and `jinja2`. Install them into a virtual environment in your working folder,
never into the system Python. Create it once per working folder:

```bash
python3 <skill>/scripts/klaviyo_to_bloomreach.py setup --venv <work>/.venv
```

It prints the install command for that venv's own pip; run it as printed:

```bash
<work>/.venv/bin/pip install beautifulsoup4 jinja2
```

On Windows the pip is `<work>\.venv\Scripts\pip`. Then pass `--venv <work>/.venv` to every other script call, as
the steps show; the script re-runs itself with the venv's Python. If the venv can't be created or the client can't
install packages, tell the user this skill can't run there and stop.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path:
`python3 <skill>/scripts/klaviyo_to_bloomreach.py` and its arguments, where `<skill>` is this skill's folder. Keep
the venv and the working files (`model.json`, `mapping.json`, `meta.json`, `ctx.json`, outputs) in your working
folder, shown below as `<work>`, never inside the skill's folder, and pass every file by its full path. Don't `cd`
into the skill's folder, and don't add `-I` or other Python flags, shell variables, `;`, redirects (`>`), `$(...)`
or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only. The script
writes its files through `--out-dir` and `--out`; otherwise read what it prints. Piping the output to `jq` or
`head` is fine.

---

## 1. Inputs

Ask for anything missing, in **one** message:

| Input | Notes |
|---|---|
| Klaviyo HTML export(s) | Klaviyo → template → *Export / Download HTML*, or the HTML pasted. One file per email; a batch is fine. |
| Target Bloomreach project | Name, URL slug or ID. **Ask every time** — never reuse a project from memory or an earlier run, never guess from the brand. |
| Per email: campaign or flow? | Flow emails (abandoned cart, browse, post-purchase) need a trigger event — see step 6. |
| Subject + preview text | Klaviyo exports don't contain them. Ask; if unknown, use a sensible draft and flag it. |
| Sender name + email | Default: copy from an existing email in the project (step 3). |

Convert while waiting for answers if you like, but make **no Loomi Connect write calls** until the
user has approved the write plan in step 4b.

## 2. Analyze

```bash
python3 <skill>/scripts/klaviyo_to_bloomreach.py analyze <export.html> --out-dir <work>/<email-slug> --venv <work>/.venv
```

Writes `model.json` (rows → columns → blocks) and prints a report. From it, note:
- `klaviyo_tags` — every tag that will need a mapping (profile properties, coupons, event data)
- `uses_event_data` / `uses_catalog_lookup` → this is a **flow email**; needs an event trigger
- `images_on_klaviyo_cdn` → rehost (step 5) — Klaviyo's CDN goes away with the account
- `hardcoded_codes` → static codes; ask whether to keep them or switch to a voucher pool
- `placeholder_copy`, `warnings` (empty links, missing images) → unfinished template; report, don't invent content
- `desktop_mobile_differences` → Klaviyo shows different content per device; the converter keeps the
  **desktop** version for all screens. Tell the user which content only appeared on one device.

## 3. Audit the Bloomreach project (Loomi Connect)

See `references/loomi-connect.md` for exact tools and rate limits. Engagement tools are capped at
3 requests/sec, bootstrap tools at 1/sec — serialize, don't fan out.

1. Resolve the project: `list_cloud_organizations` → `list_projects(org_id, url_slug=...)`, one org at a time.
2. Always: `get_mapping`, `get_customer_property_schema`, `get_consent_settings`, `list_project_variables`.
3. Sender/provider: `search_email_campaigns` / `search_scenarios` → `search_scenario_nodes(..., include_design=true)`
   on an existing email → copy `design.data.sender_name`, `sender_email`, `provider` (result is large:
   parse the saved file with Python).
4. Only if the export uses them:
   - profile properties → match each Klaviyo property to `get_customer_property_schema` (`used: true` preferred)
   - catalog loops / event data → `search_catalogs` (main catalog id is also in `get_mapping.catalogs.main`),
     `get_event_schema` (find the event + list property, e.g. `cart_update.product_list`), then **check one
     real event** with `list_customers` → `list_customer_events` and one `search_catalog_items` lookup to
     confirm the event's product IDs match catalog `_id`s
   - cart/product loops → `search_aggregates` and look for one whose `all_exposing_properties` is the cart event's
     list (e.g. `{"event_type": "cart_update", "property": "product_list"}`, usually named like "Latest cart products").
     Put its id in `mapping.event_list_aggregates`. **Use the aggregate, not the trigger event.** Every add-to-cart
     starts its own scenario run carrying only that event's snapshot, and previews pick a single event, so
     `event.product_list` often shows just one product. If no such aggregate exists, ask the user to create one in
     Bloomreach ("last" `cart_update.product_list`) — Loomi Connect can't create aggregates — or accept the event
     fallback and flag it in the report.
   - coupons → `search_voucher_pools` (only pools with `available > 0`)

## 4. Write + confirm mapping.json

Create `<work>/mapping.json` (reused for every email of the same client):

```json
{
  "customer_properties": {"first_name": "first_name", "last_name": "last_name", "email": "email", "phone_number": "phone"},
  "custom_properties":   {"Loyalty Tier": "loyalty_tier", "Unused Klaviyo Prop": null},
  "organization": {"name": "{{ project_variables.company_name }}", "full_address": "123 Main St, City, ST 00000", "url": "https://www.brand.com"},
  "unsubscribe_token": "{{ consent.page }}",
  "catalog": "products",
  "catalog_fields": {"image": "image", "title": "title", "price": "price", "url": "url"},
  "event_lists": {"item_ids": "product_list"},
  "event_list_aggregates": {"item_ids": "<aggregate id of last cart_update.product_list>"},
  "event_list_id_field": "product_id",
  "currency_symbol": "$",
  "voucher_pools": {"Klaviyo coupon name": "Bloomreach pool name"},
  "image_map": {},
  "keep_mobile_variants": false
}
```

Rules:
- `customer_properties` values come from `get_mapping.customer_properties` (the project's real names).
- `unsubscribe_token`: `{{ consent.page }}` when `get_consent_settings.enabled` is true; `{{ email.unsubscribe }}` otherwise.
- `organization.*`: prefer a project variable (`{{ project_variables.<ref> }}`) that has a value; else a literal the
  user gives you. The physical address is legally required in marketing email — the build fails without it.
- `event_list_aggregates`: preferred source for cart loops (see step 3). Without it the loop reads the trigger event and the build warns.
- `event_list_id_field`: the key inside each list entry (`product_id`), or `null` if the list holds plain IDs.
- A property mapped to `null` is rendered as an empty string and reported.

Show the user **one table** — Klaviyo field → Bloomreach field → source — and ask them to confirm or
correct it before building. For a batch, confirm once and reuse.

## 4b. Confirm the write plan

Nothing has been written yet. Before step 5, show the user the complete plan in one message and wait for an
explicit "yes":

```
Project: <project name> (<url slug>)
Will upload <N> images to the media library:
  - <email-slug>-1  ← <source URL>
  - ...
Will create <M> draft scenarios (nothing is activated or sent):
  - [Migrated – Klaviyo] <email name>   trigger: <now | event cart_update (action = add)>
  - ...
OK to go ahead?
```

If the user says no or changes anything, adjust and show the plan again. Don't start writing on a partial or
implied yes.

## 5. Rehost images

Only after the step 4b "yes". For each URL in `images_on_klaviyo_cdn` (plus any other host the client is leaving):
`import_media_file(project_id, source_url, name="<email-slug>-<n>")` → add to `mapping.image_map`:

```json
"<klaviyo url>": {"url": "<data.variants.original.url>", "width": 228, "height": 66}
```

Width/height come from `data.variants.original.dimensions` (`"228x66"`). They become the BEE image module's
natural size, so the Visual Builder doesn't have to re-measure. A plain string value (URL only) also works.
Max 2MB per image; serialize calls. If an import fails, keep the original URL and list it in the report.

## 6. Build, validate, render

Write `<work>/<email-slug>/meta.json`:

```json
{"scenario_name": "[Migrated – Klaviyo] <email name>", "node_name": "<email name>",
 "subject": "<subject, Klaviyo tags allowed>", "preheader": "<preview text>",
 "sender_name": "...", "sender_email": "...", "consent_category": "<id from get_consent_settings>",
 "provider": {"type": "global"},
 "trigger": {"type": "now"}}
```

Flow emails: `"trigger": {"type": "event", "event": "cart_update", "filter": [<atoms>]}` using the event
that carries the list in `mapping.event_lists` (e.g. `cart_update` with `action equals add`). Filter atom shape:
`{"attribute": {"type": "property", "property": "action"}, "constraint": {"type": "string", "operator": "equals", "operands": [{"type": "constant", "value": "add"}]}}`.

```bash
python3 <skill>/scripts/klaviyo_to_bloomreach.py build --model <work>/<slug>/model.json --mapping <work>/mapping.json --meta <work>/<slug>/meta.json --out-dir <work>/<slug> --venv <work>/.venv
```

Writes `bee.json`, `email.html` (compact jinja_html, ~10–15KB instead of Klaviyo's ~80KB) and
`payload.json`, and prints the change log, `errors` and `warnings`. **Fix every error and rebuild until
`"ok": true`** — errors mean the email would send broken (untranslated tags, missing unsubscribe/address,
no voucher pool, event data with a `now` trigger).

Then render it locally against real project data:

```bash
python3 <skill>/scripts/klaviyo_to_bloomreach.py render-check --html <work>/<slug>/email.html --context <work>/ctx.json --out <work>/<slug>/rendered.html --venv <work>/.venv
```

`ctx.json` = `{"customer": {...one real customer's properties...}, "event": {...one real trigger event's
properties...}, "aggregates": {"<aggregate id>": [...the customer's latest cart list...]},
"catalogs": {"<catalog>": {"<item_id>": {...item fields...}}}, "project_variables": {...}}`. Pick a customer whose
latest cart has **2+ items** so a loop that only shows one product is caught,
built from the step-3 lookups. Must return `"ok": true` with no `undefined_references`.

`ctx.json` and `rendered.html` hold a real customer's data (sandbox projects can hold real data too). Keep them
in the working directory only, never in the report or in examples, and mask names, emails and phone numbers
whenever you show rendered output (`Hi J***,`).

If the client has a headless browser available, screenshot the original export and `rendered.html` side by side
and compare.

## 7. Push + verify

1. Check the scenario is in the plan the user approved in step 4b (same project, same name). Then read
   `payload.json` and pass the object **verbatim** to `create_scenario(project_id, payload)`. Never retype or tidy it.
2. Verify: `search_scenario_nodes(project_id, scenario_id, node_id=1, include_design=true)` → `design.type == "beefree"`,
   `beefree_template` and `jinja_html` non-empty.
3. If the push fails: read the error path, fix the input (mapping/meta) or the script, rebuild, retry once.
4. Push one email at a time (rate limits). Payloads are typically 30–60KB; if one fails for size, report the size
   and give the user the built `bee.json` and `email.html` so the email can be recreated by hand in the Visual Builder.
5. Ask the user to open the email once in the Visual Builder and save it; that confirms the design and produces
   Bloomreach's own Outlook-safe HTML.

Optional rendered preview: Loomi's `generate_email_campaign_preview_link` only works on **email campaigns**
and only if the project has a default email integration — see `references/loomi-connect.md`.

## 8. Report

Per email, a short table:

| Email | Scenario | Converted | Needs attention before activating |
|---|---|---|---|

"Needs attention" always lists: empty/`#` links, placeholder images or copy, device-only content that was
dropped, static discount codes, unmapped properties, images not rehosted, the trigger to review (flow emails
usually also need a wait node and a "didn't purchase" condition added), and any project gaps (e.g. no
address variable). Link each scenario: `https://<instance>/p/<url_slug>/campaigns/scenarios/<id>` (instance and
slug from `list_projects`).

End with one line of optional upgrades the user can ask for (e.g. swap static product blocks for
recommendations, replace static codes with a voucher pool) — don't do them unasked.

---

## Rules that are easy to get wrong

- **The BEE template is the email.** The first time anyone saves in the Visual Builder, Bloomreach regenerates
  `jinja_html` from `beefree_template`. Anything that exists only in `jinja_html` is lost. The converter keeps
  both in sync (spacing is spacer rows, fonts are registered web fonts, headings are heading modules) — never
  hand-edit only `email.html`.

- **Drafts only.** Never call activation and never delete anything. If a draft is wrong, fix it with `update_scenario_node` or tell the user.
- **Project every time.** Confirm the target project per run; consent, sender and provider are looked up fresh.
- **Vouchers:** `{{ vouchers['pool'].assign_available() }}` — `voucher('pool')` does not exist.
- **Unsubscribe:** `{{ consent.page }}` (consent framework on) or `{{ email.unsubscribe }}` (legacy). Every email must have one.
- **BEE gets static links/images; jinja_html gets live tokens.** Visible text tokens (e.g. the greeting) appear in both.
  Blocks with Jinja control flow (`{% for %}`, `{% if %}`) become a custom-HTML module so the Visual Builder keeps them intact.
- **Event data needs an event trigger.** `{{ event.* }}` is empty in a `now`-triggered or broadcast send.
- **Don't fix the client's content.** Missing links, lorem ipsum and empty image slots are reported, not invented.
