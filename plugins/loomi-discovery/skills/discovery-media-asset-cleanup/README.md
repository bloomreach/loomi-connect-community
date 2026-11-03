# Discovery media asset cleanup

Reviews a Bloomreach Discovery account's media asset library (banners, in-grid images, HTML, weblayer and Clarity assets) against the media rules that use them, and returns a prioritised cleanup list: broken content on live pages first, then assets that are safe to delete.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `search_discovery_assets`, `list_site_search_media_rules`, `list_category_media_rules`, `list_global_media_rules`, `get_discovery_media_rule`, `get_discovery_multi_slot_customizations` |
| **Other requirements** | Python 3 for `scripts/asset_audit.py` (standard library only). Live link checks need a web-fetch or browser tool. |
| **Tested with** | Claude Code, against a Bloomreach demo Discovery account |
| **Maintainer** | @bloomreach |

## What it flags

- **Usage:** assets no rule uses, assets used only by disabled or expired rules, stale assets, switched-off assets that live rules still use, duplicate images.
- **Content:** placeholder, `http://`, scheme-less and placeholder-looking links and images; banner URL assets that hold text; hot-linked third-party images; hotspots without a link or alt text; unreadable content.
- **Placements:** rules pointing at assets that no longer exist, overlapping or out-of-range grid slots, multi-slot placements whose slots don't match their dimension.

## Example prompts

- "Clean up our Discovery banners: which ones are unused?"
- "Are any of our in-grid images broken or still on http?"
- "Check our multi-slot placements before the sale."

See [examples/example-report.md](examples/example-report.md).

## Notes and limitations

- Media rule lists don't say which assets a rule uses, so the skill fetches every rule in detail. Until all are fetched, unused assets are marked "unverified".
- A rule's detail shows one A/B variant; other variants' assets are listed as not checked.
- Read-only: it never deletes. Rule cleanup goes to `discovery-rule-audit`, and checking a fixed rule to `discovery-change-qa`.
