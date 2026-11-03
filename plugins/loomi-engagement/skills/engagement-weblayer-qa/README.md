# Weblayer QA

Pre-launch QA for one Bloomreach Engagement weblayer (banner). It reads the weblayer with Loomi Connect and checks every variant's HTML, CSS and JavaScript against the platform skeleton and runtime rules, tracking, old triggering code that fights Smart triggering, unsafe code and third-party loads, template parameters, Jinja, links, closing and accessibility, then the traffic split, page targeting and schedule. It returns a GO / GO WITH CAUTION / NO-GO verdict with a triage table and a fix for each issue. The static checks run in a bundled script, so the same weblayer gets the same findings every time; the assistant then judges what the script can't (where HTML values come from, unexplained loads) and loads the links.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_banners` |
| **Other requirements** | Python 3 (standard library only) for `scripts/weblayer_checks.py`; the checks can be done by hand without it. Live link checks need a web-fetch or browser tool |
| **Tested with** | Claude Code. `search_banners` (list and one weblayer by ID) was run read-only against a Bloomreach demo project on 2026-11-03, and the script was run on the result: the variant fields, the older-template skeleton and the absent schedule and smart triggering fields come from that run. The script has offline tests with synthetic fixtures. Not tested: a full run through the skill in a fresh session, link loading, and any OpenAI client. |
| **Maintainer** | Bloomreach |

## Example prompts

- "QA the 'Spring sign-up' weblayer before we turn it on."
- "Is our exit pop-up ready to go live?"
- "Check this banner for anything that would break the site."
- "Review the newsletter weblayer's code and links."

## Example output

See [examples/qa-newsletter-popup.md](examples/qa-newsletter-popup.md).

## Notes and limitations

- Read-only. It reports fixes; `engagement-weblayer-builder` can make them.
- Loomi Connect doesn't return a weblayer's Smart triggering conditions, and the banner details may not include its schedule. The skill asks for the conditions and checks the schedule with `search_banners` `serving_status`.
- It can't render or run the weblayer. The report ends with how to preview and test it.
- Weblayers built from older templates aren't failed for being old: they're checked against the runtime rules.
- To audit every weblayer, in-app message and survey in a project, use `onsite-experience-audit`.
