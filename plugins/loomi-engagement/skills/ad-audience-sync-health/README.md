# Ad audience sync health

Reviews the audiences a Bloomreach Engagement project sends to ad platforms (Facebook and Meta, Google Ads and others), its external segments and its autosegments. It finds ad-audience steps in scenarios through the project's ads integrations, traces the segment behind each one, sizes it with aggregate EQL, and flags audiences that are stale, failing, empty or below a platform's match minimum (a rule of thumb), built on an archived or missing segmentation, sent twice to the same destination, or missing an advertising consent filter where the project uses consent categories. It also flags autosegments that failed, are stale, never ran or that nothing uses. It never lists customers and never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_integrations`, `get_consent_settings`*, `search_external_segments`, `search_scenarios`, `search_scenario_nodes`*, `search_segmentations`, `search_autosegments`, `estimate_eql_cost`, `execute_analytics_eql` (* found with `search_tools` and run with `call_tool` if not listed) |
| **Other requirements** | None. Python 3 is optional, for the bundled script (standard library only) |
| **Tested with** | Claude Code, read-only, on demo projects (November 2026): `search_external_segments` (empty on both projects tried), `search_autosegments` list and one detail, `search_integrations` (Facebook Ads and Google Ads integrations present) and one scenario detail. No ad-audience scenario step was seen live, so how such steps are recognised is a heuristic the skill asks the user to confirm. `scripts/ad_audience_health.py` tested on synthetic fixtures. Not run end to end, and not tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Are our Facebook and Google audiences healthy?"
- "Which retargeting audiences are too small or out of date?"
- "Do our paid-media audiences respect advertising consent?"
- "Which autosegments failed or aren't used?"

See [examples/illustrative-ad-audiences.md](examples/illustrative-ad-audiences.md) for an example output. Its names and numbers are illustrative.

## How it works

1. Lists integrations to find ad destinations, and reads the consent settings to find the advertising category.
2. Fetches scenarios and finds steps that send to an ads integration, with the conditions and segments on the path to each.
3. Lists external segments and segmentations (archived ones included), and fetches the segmentations behind each audience to check for a consent condition.
4. Lists autosegments and fetches each one's `used_by` and job status.
5. Sizes each audience with one aggregate EQL count, and takes last-sync dates from the user.
6. [scripts/ad_audience_health.py](scripts/ad_audience_health.py) applies the thresholds in [references/rules.json](references/rules.json) and returns findings by priority.

## Notes and limitations

- **No ad-audience tool.** Loomi Connect has no tool that lists ad-platform audiences, their match rates or sync history, so last-sync checks need dates from the user or the platform.
- **External segments are inbound.** `search_external_segments` lists segments synced into Engagement from a reverse-ETL tool, and returned only `id` and `name`. The script reads destination, status, last sync and size fields only if the tool starts returning them.
- Platform minimum sizes in `references/rules.json` are rules of thumb; platforms count matched users and change their minimums.
- An empty `used_by` on an autosegment means nothing tracked uses it, not that nobody reads it.
