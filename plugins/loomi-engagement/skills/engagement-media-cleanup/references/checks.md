# Media cleanup checks

What [scripts/media_library_audit.py](../scripts/media_library_audit.py) checks and how, so the same result can be worked out by hand. Every threshold named here is a key in [rules.json](rules.json); change it there.

## How usage is found

- **Files:** a file's `_id` is part of every URL it's served from (`.../media/original/<id>`), so the script searches every saved definition for each file ID: email designs (HTML and the Visual Builder JSON in `beefree_template`), scenario node designs, SMS messages, weblayer HTML, CSS and JavaScript, in-app messages, and the content of blocks, snippets and templates. By hand, search each saved detail for the file ID.
- **Blocks and snippets:** campaigns reference them as `{{ block('<id>') }}` and `{{ snippet('<id>') }}`, so they're found by ID the same way. A file inside a block counts as used wherever that block is used, and so on through snippets: usage is followed until nothing changes, so loops can't run forever.
- **Templates** (`template_kinds`: email, SMS and app inbox templates): copying a template into a campaign leaves no reference to it, so their usage can't be traced. They're **not traceable**, never "unused". An SMS template whose message (at least `min_copy_text_chars` long) appears word for word in an SMS campaign or a scenario is reported as copied there. A file used only inside a template is **template only**.
- Editor fields (`created_by_display_name` and similar), `company_id`, `initiative_id` and each record's own `_id` are skipped, so a record never "uses" itself.

## States

| State | Meaning |
|---|---|
| `live` | Used, directly or through a block or snippet, by an active campaign, scenario, weblayer or in-app message (`live_statuses`). |
| `draft_only` | Used only by drafts or inactive content. |
| `template_only` | Used only inside a saved template. |
| `unused` | Nothing checked uses it, and every kind in `required_usage_kinds` was loaded (and, for files, every block and snippet with its content). |
| `unused_unverified` | Nothing checked uses it, but something wasn't loaded or was denied. Never delete on this. |
| `not_traceable` | A template whose usage can't be traced. |

Archived campaigns and scenarios don't count as users.

## Findings

| Code | On | Raised when | Priority |
|---|---|---|---|
| `archived_in_use` | file, asset | Archived (or in an archived folder) but used by live content (high) or a draft (medium). The image or block may stop working. | high / medium |
| `huge_image` | file | An image over `huge_image_bytes`. | high if live, else medium |
| `large_image` | file | An image over `large_image_bytes`. | medium if live, else low |
| `oversized_dimensions` | file | Width or height over `max_image_width_px`. | low |
| `insecure_url` | file | A file variant served over `http://`. | medium |
| `missing_alt` | file, content | In an email design (`alt_text_kinds`), an `<img>` with no or empty `alt`, or a Visual Builder image whose `alt` is empty. Images with width and height up to `tracking_pixel_max_px` are skipped. Each image is counted once, although email designs hold the design twice. | medium if live, else low |
| `insecure_image` | content | An image `src`, `background` attribute or CSS `url()` on `http://`. Shown as scheme, host and path only. | high if live, else medium |
| `duplicate` | file | Same name (after removing `name_noise_patterns`) and same size; or same size and dimensions with a different name, for files of at least `min_duplicate_bytes`. The one kept is the one in use, then the oldest. | low |
| `duplicate_name` | asset | Same kind and same name after removing `name_noise_patterns`. | low |
| `test_name` | file, asset | A whole word of the name is in `test_name_words`, or it contains "copy of". | low |
| `stale` | file, asset | Unused (or not traceable) and created or last edited more than `stale_days` ago. | low |

## Actions

- **fix:** live or draft content has a medium or high problem it can fix (archived in use, too heavy, missing alt text, http).
- **delete_candidate:** `unused` (verified) and stale, test-named or a duplicate.
- **review:** `unused` but recent; `unused_unverified`, `not_traceable` or `template_only`; or a duplicate or test name on something in use.
- **keep:** in use, with no findings above low.

## What this can't see

- Content outside Engagement that hot-links a file URL (a website, another tool), and files pasted into a campaign as an external URL rather than from the library.
- Usage in archived campaigns and scenarios, and in kinds that weren't loaded or were denied.
- Whether an `alt=""` is intentional: decorative images may keep an empty alt.
- File content: there's no hash, so two different images with the same name and size would be matched.
