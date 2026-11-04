# Data Hub collection audit

Audits the item collections in a Bloomreach Data Hub workspace: their configuration, fields, item types, a sample of records and their jobs. It compares related collections (staging and production, or one per locale) and returns a prioritised fix list with an owner for each: configuration drift between pairs, identifiers and required or key fields missing or sparse, values that don't fit their declared type, unused, unconfigured and dropped fields, stale or failing collections, item types that feed nothing, and catalogs pointing at missing collections.

| | |
|---|---|
| **Products** | Data Hub |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_workspaces`, `list_projects`, `search_item_collections`, `search_item_types`, `get_item_collection_configuration`, `get_datahub_system_configuration`, `compare_item_collection_configurations`*, `validate_item_collection_attribute`* (optional, writes nothing), `search_item_collection_fields`*, `search_item_collection_records`*, `search_datahub_jobs`, `search_datahub_catalogs` (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | Python 3 for `scripts/datahub_collection_audit.py` (standard library only) |
| **Tested with** | Claude Code: tool schemas and the "no Data Hub" error checked live; the audit itself run on synthetic fixtures only, because no workspace with Data Hub enabled was available |
| **Maintainer** | @bloomreach |

## Example prompts

- "Audit our Data Hub item collections."
- "Why does our staging product collection behave differently from production?"
- "Is the product data in Data Hub complete and up to date?"

See [examples/example-audit.md](examples/example-audit.md) for illustrative output.

## Notes and limitations

- Read-only. It never applies configuration changes, even the change-list `compare_item_collection_configurations` returns.
- It reports field names, fill rates and counts, never record values.
- Fill rates and type checks come from a records sample in storage order, not a random sample.
- Variant-level attributes aren't fill-checked from parent records.
- Freshness depends on the jobs read; a short job list shows only recent history.
- Thresholds, pairing words and owners are in `references/rules.json`.
