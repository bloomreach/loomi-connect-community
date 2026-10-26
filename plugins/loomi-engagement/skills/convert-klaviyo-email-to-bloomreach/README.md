# Convert Klaviyo email to Bloomreach

Migrates Klaviyo email templates into Bloomreach Engagement for agencies and partners moving clients off Klaviyo. It translates Klaviyo template tags (profile properties, catalog and cart loops, coupons, unsubscribe) to Bloomreach Jinja against the target project's real data, rebuilds the layout as an editable Visual Builder email, rehosts images from Klaviyo's CDN, and pushes each email as a **draft** scenario. The aim is a faithful 1:1 migration: no redesigns or added personalization unless you ask.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: uploads images to the media library (`import_media_file`), creates draft scenarios (`create_scenario`), and can fix a node in a scenario it created in the same run (`update_scenario_node`). Shows the full write plan and waits for a "yes" before the first write. Never activates or sends anything |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_mapping`, `get_customer_property_schema`, `get_consent_settings`*, `list_project_variables`, `get_event_schema`, `search_catalogs`, `search_catalog_items`, `search_aggregates`, `search_voucher_pools`*, `list_customers`, `list_customer_events`, `get_customer_properties`, `search_scenarios`, `search_scenario_nodes`*, `import_media_file`*, `create_scenario`, `update_scenario_node`* (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | Python 3 with `beautifulsoup4` and `jinja2`, installed with pip into a virtual environment in the working folder (the script's `setup` subcommand creates it), never the system Python. The client must be able to install packages |
| **Tested with** | Claude (claude.ai): real Klaviyo exports (campaign with product loops, split blocks and images on Klaviyo's CDN) converted, rendered and pushed as draft scenarios to demo projects, with images rehosted and the design verified after the push. Not yet tested in an OpenAI client |
| **Maintainer** | @jeffbird13-bloomreach |

## Example prompts

- "Migrate these three Klaviyo emails into our Bloomreach project."
- "Here's the HTML export of our Klaviyo abandoned-cart email. Convert it to Bloomreach."
- "We're moving a client off Klaviyo. Can you rebuild their welcome series in Engagement?"

See [examples/example-migration.md](examples/example-migration.md) for illustrative output.

## How it works

1. **Analyze** the export with `scripts/klaviyo_to_bloomreach.py analyze`: Klaviyo tags used, images on Klaviyo's CDN, flow/event data, dead links, placeholder copy, desktop-only or mobile-only content, hard-coded discount codes.
2. **Audit** the Bloomreach project (read-only) and map every Klaviyo field to a real project field. You confirm the mapping table once per client.
3. **Confirm the write plan**: every image upload and draft scenario is listed, and nothing is written until you say yes.
4. **Rehost images, build and validate**: the build fails on untranslated tags, a missing unsubscribe link or postal address, or event data with the wrong trigger. A local render check uses one real customer's data.
5. **Push** each email as a draft scenario and verify the Visual Builder design arrived intact.
6. **Report** per email: what converted and what needs attention before activating.

## Notes and limitations

- **Drafts only.** Flow emails (abandoned cart, browse, post-purchase) get an event trigger, but usually still need a wait node and a "didn't purchase" condition added before launch. The report says so.
- **Cart loops** read a "last `cart_update.product_list`" aggregate, because the trigger event only holds that one add-to-cart. Loomi Connect can't create aggregates; if none exists, the skill asks you to create one or flags the fallback.
- **Desktop and mobile variants:** Klaviyo can show different content per device. The converter keeps the desktop version for all screens and lists what was dropped.
- **Client content isn't fixed.** Empty links, lorem ipsum and empty image slots are reported, not invented.
- **Customer data:** the render check uses one real customer's properties, kept in the working directory only and masked in anything shown.
- **Large emails:** converted payloads are usually 30–60 KB. If a push fails for size, the skill reports it and hands over the built files.
- Open each migrated email once in the Visual Builder and save it; Bloomreach then regenerates its own Outlook-safe HTML.
