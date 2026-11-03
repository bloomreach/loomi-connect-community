# Discovery catalog configuration audit

Audits a Bloomreach Discovery catalog's attribute and index configuration: the settings underneath every search and category page. It finds internal fields such as margin or cost returned to the storefront or shown as filters, key attributes that aren't searchable, numeric and identifier attributes that are, custom attributes that duplicate reserved ones, configured attributes the feed never fills, key attributes missing from products, and risky variant and index settings, then returns a prioritised fix list with the dashboard change for each.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `search_discovery_catalogs`, `get_discovery_catalog_config`*, `get_discovery_catalog_reserved_attributes`*, `search_discovery_catalog_products` (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | Python 3 for `scripts/config_audit.py` (standard library only) |
| **Tested with** | Claude Code, against a Bloomreach demo account |
| **Maintainer** | @bloomreach |

## Example prompts

- "Audit our Discovery catalog configuration."
- "Is any internal data like margin exposed in our search results?"
- "Why isn't brand searchable? Check our attribute settings."

See [examples/example-audit.md](examples/example-audit.md) for illustrative output.

## Notes and limitations

- Read-only. It gives the setting to change in the Discovery dashboard; a reindex may be needed afterwards.
- It reports attribute names and fill rates only, never values, so internal fields such as margin aren't repeated.
- Fill rates come from a few pages of products in feed order, not a random sample.
- Internal fields are spotted by name (`internal_words` in `references/rules.json`); add words your catalog uses.
- Range facet settings aren't in the catalog config; `facet-optimizer` reviews numeric facets.
