# Bloomreach Jinja writer

Writes, fixes and explains Bloomreach Engagement Jinja for weblayers, emails, SMS, push and scenarios. Bloomreach Jinja has rules that standard Jinja doesn't, such as constant-string engine and aggregate IDs, generators that need `| list`, loops that need `{% append %}`, and no Python datetime. This skill follows them and checks every snippet against a checklist before returning it. With Loomi Connect connected, it looks up the project's real recommendation engines, aggregates, catalogs, reports and customer attributes, so the code uses IDs and field names that exist.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | Optional: `list_cloud_organizations`, `list_projects`, `search_recommendations`, `search_aggregates`, `search_catalogs`, `search_catalog_items`, `search_reports`, `search_segmentations`, `get_customer_property_schema`, `list_project_variables` |
| **Other requirements** | None. Works without Loomi Connect, using placeholders for IDs |
| **Tested with** | Claude Code: the Jinja reference has been used day to day to build live weblayers. Every lookup tool in the table was run read-only against a test project on 2026-10-30 (`search_recommendations`, `search_aggregates` list and detail, `search_catalogs` list and detail, `search_catalog_items`, `search_reports`, `search_segmentations`, `get_customer_property_schema`, `list_project_variables`), and the aggregate-shape and project-variable steps come from that run. Rendering isn't tested by the skill: Loomi Connect only previews existing campaigns. Not tested in an OpenAI client. |
| **Maintainer** | @CWildeBloomreach |

## Example prompts

- "Write the Jinja for a weblayer that shows four recommendations, with the engine as a parameter."
- "Show the customer's cart items from our cart aggregate in an abandoned cart email."
- "Add '23 people bought this today' social proof from a report."
- "Why won't this Jinja save? It says the recommendation ID is invalid."
- "Format this timestamp as a date in Bloomreach Jinja."

## Example output

See [examples/cart-recommendations-weblayer.md](examples/cart-recommendations-weblayer.md).

## Notes and limitations

- The reference was checked against the Bloomreach documentation on 2026-04-17. `expressions` and direct `predictions(...)` calls aren't documented, but work in practice.
- The skill only returns code. It never saves anything to Bloomreach.
- Preview the code in Bloomreach against a test customer before it goes live. The skill can't render Bloomreach Jinja itself.
