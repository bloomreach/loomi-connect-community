# Implementation readiness

A go-live checklist for a new Bloomreach account. It answers "are we ready to launch?" with red, amber and green rows, blockers first, each with the evidence, the fix and an owner (developer, merchandiser or CRM):

- **Discovery tracking:** the launch pixel types send events, and their issue rates (via `data-feed-health`);
- **Discovery catalog:** feed and index jobs run (via `data-feed-health`), products carry title, price, URL, image and category, and the basic attributes are searchable and facetable;
- **Discovery search:** search and category API traffic arrives;
- **Engagement tracking:** the core events (session start, product view, cart update, checkout, purchase, or the project's own names) exist, are received and carry the expected properties;
- **Engagement identity and consent:** a permanent customer ID and consent categories;
- **Engagement catalog and flows:** a product catalog with items, and welcome and cart abandonment scenarios.

It's the launch checklist; for ongoing health it hands off to [data-feed-health](../data-feed-health/) and `engagement-tracking-health`. It never changes anything.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_sites`, `search_discovery_catalogs`, `get_pixel_health_status`, `get_pixel_event_stream`, `get_pixel_event_details`, `search_discovery_catalog_jobs`*, `get_discovery_catalog_config`*, `search_discovery_catalog_products`, `get_discovery_api_requests`, `list_cloud_organizations`, `list_projects`, `get_event_schema`, `get_customer_schema`, `get_consent_settings`*, `search_catalogs`, `search_catalog_items`, `get_mapping`, `search_scenarios` (* via `search_tools` and `call_tool`) |
| **Other requirements** | Python 3 for `scripts/readiness_checks.py` (optional; standard library only) |
| **Tested with** | Claude Code (read-only calls in November 2026 to check response shapes: pixel health, catalog config, product records and API request counts on a Bloomreach demo Discovery account; event schema, customer ID schema, consent settings, catalogs, catalog items and scenarios on a demo Engagement project. Not yet run end to end on a real new implementation. The script is tested on synthetic fixtures) |
| **Maintainer** | Bloomreach |

## Example prompts

- "We go live in two weeks. Is the Bloomreach implementation ready?"
- "Run a launch checklist for the new account: pixel, catalog, events, consent, flows."
- "What's still missing before go-live, and who needs to fix it?"

See [examples/example-readiness.md](examples/example-readiness.md) for an illustrative checklist.

## Scripts

- `scripts/readiness_checks.py`: reads the saved pixel health, catalog config, product sample, API request counts, event schema, customer ID schema, consent settings, catalog list, catalog items and scenario list, adds rows from other skills (`--item`), and prints the checklist with a verdict. Expected events, fields, words and statuses are in `references/rules.json`. Standard library only; no network access.

## Notes and limitations

- Pixel issue rates and feed job health are rated by `data-feed-health`'s rules, not this skill's, so the two never disagree.
- The Discovery catalog config has no "sortable" setting; sorting by price depends on a numeric price, which the product field check covers.
- Whether the site identifies customers and records consent correctly can't be seen through Loomi Connect; the skill lists these as manual checks.
- Flows are found by name. If the team names them differently, the skill asks before reporting them missing.
- Before launch, "no events yet" is AMBER (expected, but must be seen on launch day); after launch it's RED.
