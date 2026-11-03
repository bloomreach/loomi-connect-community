# Discovery hidden configuration audit

Audits two Bloomreach Discovery settings that change search and category results without showing up in the usual rule reviews: **audiences** (the targeting behind personalised rules) and **API parameter overrides** (global rewrites of `sort`, `fq`, `efq`, `rows`, `fl` and similar). It finds audiences that can't match, overlap, duplicate each other, match far more than intended or that nothing uses, maps which rules are personalised for which audience, and flags overrides that are expired, forgotten, duplicated or that distort every request. You get a prioritised cleanup list. It never changes anything.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `list_discovery_audiences`, `list_site_search_ranking_rules`, `list_category_ranking_rules`, `list_ranking_rules_global`, `list_site_search_media_rules`, `list_category_media_rules`, `list_global_media_rules`, `list_site_search_facets`, `list_category_facets`, `list_facets_global`, `get_facet_rule`, `search_redirects`, `get_ranking_rule`, `get_discovery_media_rule`, `list_api_params` |
| **Other requirements** | Python 3 for `scripts/hidden_config_audit.py` (standard library only) |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account (audiences; that account had no API parameter overrides) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Audit our Discovery audiences: which ones are unused or broken?"
- "Why do some shoppers see different search results?"
- "Do we have any API parameter overrides we've forgotten about?"
- "Clean up our personalisation targeting in Discovery"

See [examples/example-audit.md](examples/example-audit.md) for illustrative output.

## Notes and limitations

- **Personalised rules are traced through the rule lists' `audience_ids` filter**, because the lists show `audienceName: null`. Facet rules and redirects have no such filter; the skill reports how many rules it couldn't account for.
- **Engagement-segment audiences** depend on an Engagement segmentation that Discovery can't check. They're listed for you to verify in Engagement.
- **API parameter overrides:** the record shape wasn't seen with data during testing. The script accepts the likely shapes and reports any override it can't read, rather than guessing.
- Audience matching is assumed to treat values in one dimension as alternatives and separate dimensions as all required.
