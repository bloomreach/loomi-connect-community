# Media asset cleanup: checks

What each finding means, its severity and the fix. `scripts/asset_audit.py` does all of them except loading links; the thresholds and word lists are in `references/rules.json`. Without scripts, apply the same rules by hand.

## How assets and rules connect (tested on a demo account, November 2026)

- `search_discovery_assets` lists assets with their whole content: `sharedData` is a JSON **string**. List pages already include it, so detail calls aren't needed.
  - Banners (`dataType: "banners"`): `banner.bannerType` is `image_upload` or `image_url` (an image URL in `image_url.imageUrl`), `banner_url`, or `html`. For `html`, `image_url.imageUrl` holds the HTML; for `banner_url` it should hold a URL but can hold plain text. `banner_hotspot` is a list of clickable regions, each with `url` and `altText`. `banner.enabled` can switch an asset off.
  - Weblayers (`dataType: "weblayer"`) are Engagement weblayers exposed to Discovery. Their page targeting is in `trigger.include_pages[].url`.
  - Each asset record also has `user` (an editor's email address). Never repeat it.
- Media rule **lists** don't say which assets a rule uses. Only `get_discovery_media_rule` does: `customizationItems.campaign.bannerId` (the top banner) and `customizationItems.content_in_grid[]` (grid placements, each with `bannerId`, `slots`, `slotType` `single` or `multi`, `dimension` such as `2x2`, and `pcs`). `sharedId` is the top banner's ID only.
- `get_discovery_multi_slot_customizations` returns only each rule's `id`, `name` and `queries`, not its slots: fetch those rules in detail.
- `matchType` comes back as `EXACT_MATCH` from some calls and `exact_match` from others.

## Where an asset is used

| Finding | Severity | Fix |
|---|---|---|
| `unused`: no media rule uses it | low | Delete it in the Discovery dashboard if nobody needs it |
| `unused_unverified`: no fetched rule uses it, but some rules weren't fetched in detail | low | Fetch the rules listed under `not_checked.rules_without_detail` before deleting anything |
| `inactive_only`: used only by disabled or expired rules | low | Delete the rules first (`discovery-rule-audit`), then the asset |
| `stale`: not changed for more than `stale_days` and not used by a live rule | low | Review and delete |
| `disabled_but_used`: the asset is switched off but a live rule uses it | medium | Switch it on, or remove it from the rule |
| `duplicate_image`: same image as another asset | low | Keep one and point rules at it |

A **live** rule is enabled and not expired (`durationTag` other than `expired`).

## Asset content

| Finding | Severity | Fix |
|---|---|---|
| `placeholder_link`: a link, image or weblayer page on `example.com`, `yourdomain.com` and the like | high on a live asset, otherwise medium | Use the real URL |
| `missing_scheme`: a link with no `https://` | medium | Write it in full |
| `no_tls`: an `http://` image or link | medium | Use `https://` (browsers block mixed content on https sites) |
| `placeholder_words`: `test`, `todo`, `dummy` … in the path | medium | Confirm the real URL |
| `not_a_url`: a `banner_url` asset that holds text | medium | Fix the asset type or content |
| `empty_link`, `empty_content`, `hotspot_without_link` | medium | Add the missing link or content |
| `unreadable`: the content isn't valid JSON | medium | Open the asset in the dashboard and re-save it |
| `hotlinked_image`: image hosted outside Bloomreach | low | Upload it, so a third party can't change or remove it |
| `hotspot_alt`: a hotspot link with no alt text | low | Add alt text for screen readers |
| `asset_disabled` | low | Delete it if nothing needs it |

## Media rule placements

| Finding | Severity | Fix |
|---|---|---|
| `missing_asset`: the rule uses an asset that isn't in the library | high on a live rule, otherwise medium | Pick a current asset, or retire the rule |
| `overlapping_slots`: two placements in one rule share a slot | high on a live rule, otherwise medium | Move one of them |
| `slot_out_of_range`: a slot outside 1–72 | medium | Use a slot in range |
| `duplicate_slot`, `empty_placement` | medium | Fix the placement |
| `multi_slot_shape`: a multi-slot placement covers a different number of slots than its dimension (`2x2` = 4) | medium | Fix the slots or the dimension |
| `variants_not_checked`: an A/B rule with several variants | low | The detail returns one variant; check the others in the dashboard |

Rule changes go through `discovery-rule-audit` (cleanup) or `discovery-change-qa` (before switching a fix on).

## Loading links

`links_to_load` lists unique http(s) image and link URLs, those in live assets first, capped at `max_links_to_load`. Load them only if the client can, one method after another:

1. A web-fetch tool: `HEAD`, then `GET` if needed, following redirects.
2. A browser tool, if the web-fetch tool is missing or refuses the URL. Open the link in a new tab and read the real status where the tool can run JavaScript (`performance.getEntriesByType('navigation')[0].responseStatus`); otherwise read the title and text. Never click, sign in, accept cookies or submit anything, and wait for any site approval the client asks for.
3. Otherwise mark it **not checked**.

Results: 404, 410 or 5xx (or an error page) on a live asset's image or link = **high**, elsewhere **medium**. 401, 403, 429, bot challenges ("Just a moment…", "Verify you are human") and timeouts = **not checked**, never broken.
