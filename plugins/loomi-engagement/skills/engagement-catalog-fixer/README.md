# Engagement catalog fixer

Applies fixes to items in a Bloomreach Engagement catalog, the one behind recommendations, emails and weblayers: prices and sale prices, stock that says in stock when the site has sold out, product URLs, images and titles. The fixes come from [catalog-parity-check](../../../loomi-platform/skills/catalog-parity-check/)'s findings or from a list you give. It reads each item first, plans every change with its before and after state and an undo that restores the whole item, shows the plan, writes only after you say yes to each batch, and reads each item back to check it. It deletes an item only when you ask for that item.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: updates catalog items (`upsert_catalog_item`; `import_catalog_items` for large v2 batches only when switched on) and, only when you ask for a specific item, deletes it (`delete_catalog_item`), each batch after you confirm. Never changes margin or cost fields, never adds fields or changes the catalog's schema or settings, never creates items |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_catalogs`, `get_catalog_configuration`*, `get_catalog_item`*, `search_catalog_items`, `list_catalog_jobs`; writes: `upsert_catalog_item`*, `import_catalog_items`*, `delete_catalog_item`* (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | Python 3 for `scripts/catalog_fix_plan.py` (optional; standard library only) |
| **Tested with** | Claude Code: the write tools' schemas and descriptions were read with `search_tools`, and catalog details, item lookups (found and not found) and item pages were checked read-only against a demo project in November 2026. No write was made while building the skill. The script is tested on synthetic fixtures. Not yet tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Fix the price and stock mismatches the catalog parity check found."
- "Mark P200 out of stock in the Engagement catalog and set its price to 45."
- "Remove the discontinued item OLD1 from our Engagement product catalog."

See [examples/fix-parity-findings.md](examples/fix-parity-findings.md) for an illustrative run.

## How it works

1. **Fixes:** the parity check's output JSON (choose which checks to fix), or a change file of your own.
2. **Read:** each item with `get_catalog_item`, and the catalog's fields with `search_catalogs` (and `get_catalog_configuration` for v2).
3. **Plan:** `catalog_fix_plan.py plan` keeps every property as read and changes only the fixed fields, writes stock in the item's own words, and blocks protected fields, fields the catalog doesn't define, items that aren't in the catalog and deletes you didn't ask for.
4. **Confirm and write:** one batch at a time (deletes on their own), with the exact calls from the plan.
5. **Verify:** `catalog_fix_plan.py verify` reads each item back and reports `in_place`, `not_in_place` (including properties a write wiped) or `gone`.

## Notes and limitations

- **Upserts replace the whole item.** `upsert_catalog_item`'s description says "Missing fields are not left in place on replace", and items carrying a single property after earlier partial writes were seen in a demo catalog. So every payload carries the full record. `import_catalog_items` is off by default (`use_import_for_v2` in rules.json): its operation shape hasn't been confirmed by a live write. With `--use-import` it's used only on v2 catalogs, with full records, and the first import is a single item verified before the rest. Its field-level paths are untested and never used.
- **Fixes don't last past the next import** unless the feed is fixed too. Use [data-feed-health](../../../loomi-platform/skills/data-feed-health/) for import freshness.
- **No new items.** Products missing from Engagement need the feed or import; an upsert of a partial record would create a half-empty item.
- **Lookups by ID reach every item;** browsing with `search_catalog_items` only reaches the first 1,000.
- **Data Hub-managed catalogs** refuse Engagement writes; the skill stops and says so.
- **URLs and images** must be `https://`; a new host that differs from the item's current one is a warning.
- **Undo** writes the whole old record, so the skill reads the item again first and asks again if it changed since the write.
- The plan file holds margin and cost values (an upsert must send them back unchanged); the skill never shows them.
