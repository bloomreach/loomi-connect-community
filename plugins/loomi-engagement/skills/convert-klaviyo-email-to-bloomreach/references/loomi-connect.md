# Loomi Connect — tools used by this skill (verified Oct 2026)

Loomi Connect only shows part of its ~190 tools directly. If a tool below isn't in your tool list, find it with
`search_tools("<name or task>")` and run it with `call_tool(name, arguments)`.

## Rate limits (per user)

| Bucket | Limit | Applies to |
|---|---|---|
| Bootstrap | **1 / sec** | `list_cloud_organizations`, `list_projects`, `list_workspaces` |
| Engagement | 3 / sec, 60 / min | everything project-scoped |
| Feedback | 1 / 10 sec | `submit_llm_feedback` |

A 429 says how long to wait. Serialize calls rather than firing them in parallel.

## Renamed tools (older skills use the left column — those calls fail)

| Old | Current |
|---|---|
| `list_aggregates` | `search_aggregates` (+ `search_running_aggregates`, `search_expressions`) |
| `list_recommendations` / `get_recommendation` | `search_recommendations` (pass `recommendation_id` for detail) |
| `list_voucher_pools` / `get_voucher_pool` | `search_voucher_pools` (pass `pool_id` for detail + `used_by`) |
| `list_catalogs` / `get_catalog` | `search_catalogs` (pass `catalog_id` for fields); v2 catalogs also `get_catalog_configuration` |
| `list_catalog_items` | `search_catalog_items` / `get_catalog_item` |

## Audit (read-only)

| Tool | Use |
|---|---|
| `list_cloud_organizations` → `list_projects(cloud_organization_id, url_slug)` | resolve project (1/sec) |
| `get_mapping` | real names for first_name/email/…, main catalog id + column map, standard events, consent ids |
| `get_customer_property_schema` | all properties; prefer `used: true` |
| `get_event_schema` | events + properties (large — parse the saved file with Python) |
| `get_consent_settings` | `enabled`, categories (pick the email/newsletter one), `general_consent.email` |
| `list_project_variables` | `{{ project_variables.<reference> }}` candidates (company name, address, URLs) |
| `search_catalogs`, `search_catalog_items(query=<id>)` | confirm event product IDs match catalog `_id` |
| `list_customers`, `list_customer_events(event_types=[...])`, `get_customer_properties` | real data for render-check |
| `search_voucher_pools` | pools with `available > 0` |
| `search_custom_rows`, `search_email_blocks`, `search_snippets` | client's existing headers/footers/blocks (optional reuse) |
| `search_scenarios` → `search_scenario_nodes(…, node_id, include_design=true)` | copy sender + `provider` from an existing email |
| `search_integrations` | lists integrations, but the IDs are **not** accepted as email `provider.integration_id` (see below) |

## Write

| Tool | Notes |
|---|---|
| `import_media_file(project_id, source_url, name)` | public URL only; 2MB images; returns `data.variants.original.url` (brxcdn.com) and `.dimensions` (`"228x66"`) |
| `create_scenario(project_id, payload)` | always draft; `send-email-action` with `design.type: "beefree"` keeps the Visual Builder design |
| `update_scenario_node(project_id, scenario_id, node_id, patch)` | fix one node in place (shallow merge — send the whole `design` object) |
| `create_email_campaign` | `design.type: "raw"` only (no Visual Builder). Not used by this skill unless the user asks; add it to the step 4b write plan first |

This skill never calls `delete_*` tools. If a draft it created is wrong, fix it with `update_scenario_node` or tell the user.

## Verified gotchas

- **Provider:** `{"type": "global"}` (copied from existing nodes) means "project default email integration".
  The explicit form is `{"type": "integration", "integration_id": "<id>"}`, but `search_integrations` IDs are
  rejected ("Integration not found"). Copy the provider from an existing email in the project.
- **Preview:** `generate_email_campaign_preview_link(project_id, campaign_id, customer_id)` works on email
  campaigns only, and fails with "Email integration is not set" when the project has no default email
  integration. `event.*` data never renders in a preview.
- **Payload size:** `create_scenario` accepted 28–30KB payloads (BEE + jinja_html) intact in testing. Full
  Klaviyo-converted emails are 40–60KB; if one fails, report the size.
- **Visual Builder round-trip (verified):** a pushed email opened, saved and previewed in the Visual Builder with
  custom-HTML (Jinja loop), heading, text-with-token, button, image, social and spacer modules. Saving regenerates
  `jinja_html` from the BEE template.
- **Consent:** when `general_consent.email` is false, a `consent_category` is required.
- **Scenario connections:** trigger source `connector_index: 0`, destination 0; `last_node_id` = highest node id.
