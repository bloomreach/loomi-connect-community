# Playbook: catalog truth

Makes the same product show the same price, stock and link in search, recommendations and email. Four existing skills run in order: compare the Discovery and Engagement catalogs, find wrong prices across the Discovery catalog, check page-one products and top sellers at variant level, and fix the Engagement items that are wrong. The Discovery-side problems go to the feed and pricing teams as one list, and after a wait the parity check runs again to see whether the fixes held. A hand-off file in your working folder carries the findings, the changes and the dates between stages.

| | |
|---|---|
| **Products** | Discovery and Engagement |
| **Access** | **Writes**, through its stage skills only: `engagement-catalog-fixer` updates Engagement catalog items (live for recommendations and emails within minutes; each upsert replaces the whole item with the planned record), each batch only after its own explicit "yes". This playbook never deletes items |
| **Loomi Connect tools** | Those of its stage skills. Writes: `upsert_catalog_item`, `import_catalog_items` (v2 batches, off by default) |
| **Other requirements** | The `loomi-platform`, `loomi-product-data`, `loomi-discovery` and `loomi-engagement` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Our emails show prices that don't match the site. Find what's out of sync and fix it."
- "Check our product data is right everywhere: search, recommendations and email."
- "Carry on with the catalog truth run: has the feed team's fix landed?" (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| parity | `catalog-parity-check` | now |
| prices | `price-anomaly-finder` | now |
| variants | `discovery-variant-health` | now |
| fix | `engagement-catalog-fixer` | now, after confirmations |
| recheck | `catalog-parity-check` | `recheck_after_days` after the fix |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records each failing check as a finding with its owner, reads the fixer's plan and verify files into the change log, and prints what's next and when. See [examples/price-drift.md](examples/price-drift.md).

## Notes and limitations

- Only the Engagement side is fixed here. No Loomi Connect tool writes to the Discovery product feed, so Discovery-side fixes go to the feed and pricing teams as a list.
- Engagement fixes last until the next catalog import overwrites them. The recheck tells you whether they held; if they didn't, the import's cadence or fields need fixing (`data-feed-health`).
- The recheck is a parity check: it doesn't re-run the price and variant checks inside Discovery. Re-run `price-anomaly-finder` or `discovery-variant-health` for those.
- A catalog managed by a Data Hub item collection refuses Engagement writes; the fix stage then stops.
- Findings are per check, not per product: the saved files hold the products.
