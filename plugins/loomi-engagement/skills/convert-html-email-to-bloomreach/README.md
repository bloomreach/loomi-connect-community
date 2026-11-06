# Convert HTML email to Bloomreach

Migrates HTML email templates from any email platform into Bloomreach Engagement. It detects where the export came from (Mailchimp, Salesforce Marketing Cloud, HubSpot, Braze, Iterable, ActiveCampaign or plain HTML), translates the common merge tags by itself, and has you translate the rest (AMPscript, Liquid and Handlebars logic) into Bloomreach Jinja against the target project's real data, before anything is built. It rebuilds the layout as an editable Visual Builder email, rehosts images from the old platform, and pushes each email as a **draft** scenario. The aim is a faithful 1:1 migration: no redesigns or added personalization unless you ask.

It's the general-purpose sibling of `convert-klaviyo-email-to-bloomreach`, and the base for ESP-specific versions: each ESP's rules sit in one reference file and three places in the script.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: uploads images to the media library (`import_media_file`), creates draft scenarios (`create_scenario`), and can fix a node in a scenario it created in the same run (`update_scenario_node`). Can create a raw-HTML email campaign (`create_email_campaign`) only if you ask; it's added to the write plan first. Shows the full write plan and waits for a "yes" before the first write. Never activates or sends anything |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_mapping`, `get_customer_property_schema`, `get_consent_settings`*, `list_project_variables`, `get_event_schema`, `search_catalogs`, `search_catalog_items`, `search_aggregates`, `search_voucher_pools`*, `list_customers`, `list_customer_events`, `get_customer_properties`, `search_scenarios`, `search_email_campaigns`, `search_scenario_nodes`*, `import_media_file`*, `create_scenario`, `update_scenario_node`* (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | Python 3 with `beautifulsoup4` and `jinja2`, installed with pip into a virtual environment in the working folder (the script's `setup` subcommand creates it), never the system Python. The client must be able to install packages |
| **Tested with** | Synthetic exports for each supported ESP syntax (in the repo's tests), and 158 public open-source email templates (Mailchimp blueprints, Cerberus, Neopolitan and others) analyzed and built with no crashes, with a sample rendered side by side with the originals. Not yet tested against real customer exports from SFMC, HubSpot, Braze, Iterable or ActiveCampaign, or pushed from an OpenAI client |
| **Maintainer** | @jeffbird13-bloomreach |

## Example prompts

- "Migrate these Mailchimp emails into our Bloomreach project."
- "Here's the HTML of our Salesforce Marketing Cloud welcome email. Convert it to Bloomreach."
- "We're moving a client off HubSpot. Can you rebuild their newsletter template in Engagement?"
- "Convert this HTML email into a Bloomreach draft scenario."

See [examples/example-migration.md](examples/example-migration.md) for illustrative output.

## How it works

1. **Analyze** the export with `scripts/html_email_to_bloomreach.py analyze`: the ESP it came from, every template token (with the automatic translation, or a flag that it needs one), images on the ESP's servers, dead links, placeholder copy, hard-coded discount codes, and conditions that span several blocks.
2. **Audit** the Bloomreach project (read-only) and write the mapping: project fields for each source field, and a Bloomreach Jinja translation for each token the script can't translate by itself. You confirm the mapping once per client.
3. **Confirm the write plan**: every image upload and draft scenario is listed, and nothing is written until you say yes.
4. **Rehost images, build and validate**: the build fails on an untranslated token, leftover source syntax, a Jinja syntax error, a missing unsubscribe link or postal address, or event data with the wrong trigger. A local render check uses one real customer's data.
5. **Push** each email as a draft scenario and verify the Visual Builder design arrived intact.
6. **Report** per email: what converted and what needs attention before activating.

## Notes and limitations

- **Logic is translated with you, not guessed.** Simple merge tags, unsubscribe and view-in-browser links, company details and the year are translated automatically. AMPscript blocks, loops, data-extension lookups, connected content and anything else with logic fail the build until each one has a translation in the mapping, which you confirm.
- **Layout is rebuilt from the HTML structure.** Nested tables, hybrid (inline-block) columns and div layouts are recognised; text, images, buttons, dividers, spacers and social icons become native Visual Builder modules. Up to four columns per row; deeper nesting inside a column is stacked. Background images and decorative borders aren't carried over and are reported.
- **Conditions that wrap several blocks** (for example a section shown to one segment) can't stay as one condition in the Visual Builder. The skill asks whether to show that content to everyone or rebuild the condition by hand.
- **Visual Builder format.** The `beefree_template` JSON is the Visual Builder's own template format. Loomi Connect's published `scenario-write-best-practices` guide documents it: `design.type: "beefree"`, with the Visual Builder JSON in `design.data.beefree_template`. The module-level rules in `references/bee-schema.md` aren't published; they were observed by pushing emails through `create_scenario` and opening them in the editor.
- **Drafts only.** Flow emails get an event trigger, but usually still need a wait node and an exit condition added before launch. The report says so.
- **Client content isn't fixed.** Empty links, lorem ipsum and empty image slots are reported, not invented.
- **Customer data:** the render check uses one real customer's properties, kept in the working directory only and masked in anything shown.
- **Klaviyo exports:** use `convert-klaviyo-email-to-bloomreach`, which understands Klaviyo's block structure in more depth. This skill tells you when it sees one.
- **Making an ESP-specific version:** `references/esp-syntax.md` ends with where each ESP's rules live in the script and how to add tests, so a fork can go deeper on one platform.
- Open each migrated email once in the Visual Builder and save it; Bloomreach then regenerates its own Outlook-safe HTML.
