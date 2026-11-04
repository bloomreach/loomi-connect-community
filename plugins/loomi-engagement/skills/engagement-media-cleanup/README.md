# Engagement media cleanup

Audits a Bloomreach Engagement project's media library and reusable content (uploaded files and images, HTML blocks, snippets, and email, SMS and app inbox templates) against the emails, scenarios, SMS, weblayers and in-app messages that use them. It follows references through blocks and snippets, and returns three lists: problems to fix on live content (archived files still in use, images too heavy for email, missing alt text, images on `http://`), verified-unused items to delete (old, test-looking or duplicate), and items to review. It never deletes or changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_directory`*, `search_files`*, `search_email_blocks`*, `search_snippets`*, `search_email_assets`*, `search_sms_assets`*, `search_app_inbox_designs`*, `search_email_campaigns`, `search_scenarios`, `search_sms_campaigns`, `search_banners`, `search_in_app_messages` (* found with `search_tools` and run with `call_tool`) |
| **Other requirements** | None. Python 3 is optional, for the bundled script (standard library only) |
| **Tested with** | Claude Code, read-only, on a demo project: `get_directory` (root), `search_files`, `search_email_blocks`, `search_snippets`, `search_sms_assets` and `search_app_inbox_designs` (lists) and one email campaign detail with `include_design=True`, to confirm file fields, wrappers and where image URLs and alt text sit. The script was tested on synthetic responses. Scenario, weblayer and in-app message details were not fetched live. Not run end to end, and not tested in an OpenAI client. |
| **Maintainer** | Bloomreach |

## Example prompts

- "Clean up our Engagement media library: which images aren't used anywhere?"
- "Are any of our email images too big, or missing alt text?"
- "Find duplicate images and test blocks we can delete."
- "Which blocks and snippets are still used by live campaigns?"

See [examples/illustrative-media-cleanup.md](examples/illustrative-media-cleanup.md) for an example output. Every name and number in it is fictional.

## How it works

1. Browses every folder of the file library with `get_directory`, and lists blocks, snippets and templates, fetching each block and snippet with its content.
2. Fetches the content that can use them: email campaigns with `include_design=True`, scenarios with `include_node_designs=True`, SMS campaigns, weblayers and in-app messages, asking first when that's many calls.
3. [scripts/media_library_audit.py](scripts/media_library_audit.py) finds each file by the ID in its URL and each block and snippet by `block('<id>')` and `snippet('<id>')`, follows them to live content, and applies the checks in [references/checks.md](references/checks.md) with the thresholds in [references/rules.json](references/rules.json).
4. Returns the fix, delete and review lists and what wasn't checked.

## Notes and limitations

- Email, SMS and app inbox templates are copied into campaigns when used, so their usage can't be traced; they're listed for review by age and name, never as unused. SMS templates are matched by identical message text.
- "Unused" needs every kind of content loaded. Anything denied (403) or skipped makes it "unused (unverified)".
- There's no file hash, so duplicates are matched by name and size, or by size and dimensions.
- Scenario, campaign and template cleanup belongs to [engagement-asset-cleanup](../engagement-asset-cleanup/); Discovery banners to `discovery-media-asset-cleanup`.
