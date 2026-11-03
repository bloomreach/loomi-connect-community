---
name: onsite-experience-audit
description: Audits Bloomreach Engagement on-site and in-app experiences with Loomi Connect, covering web layers (banners), in-app messages, surveys and web experiments. It flags experiences that are still active after their end date or have no end date, overlapping experiences on the same pages or audiences, experiences never A/B tested, poor performers where banner stats are tracked, and stale drafts and test copies, then returns a prioritised cleanup and test list. Use when the user asks for a web layer, weblayer, banner, pop-up, in-app message, survey or on-site experiment audit, cleanup or inventory, which on-site campaigns are live, or what to A/B test on site.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement). Python 3 is optional, for the bundled audit script.
metadata:
  author: bloomreach
  version: "0.1.4"
  products: engagement
  access: read-only
---

# On-site experience audit

## What this does

Takes stock of every on-site and in-app experience in one Engagement project and returns a **cleanup list** and a **test list**. It checks:

| Check | Why it matters |
|---|---|
| **Expired but still active**, or **active with no end date** | Old promotions keep showing, and forgotten experiences slow pages and confuse reporting |
| **Overlapping** experiences on the same pages and audience | Visitors see two pop-ups at once, or one hides another; results can't be attributed |
| **Never A/B tested** (one variant, no control group) | Nobody knows whether it earns money or costs it |
| **Poor results**, where banner events are tracked | Low click-through or high close rate means it's annoying people |
| **Drafts and test copies** left lying around | Clutter makes the live ones hard to find and easy to break |

It never changes anything.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Project | `list_cloud_organizations`, `list_projects` |
| Web layers (banners) | `search_banners` |
| In-app messages | `search_in_app_messages` |
| Surveys | `search_surveys` |
| Web experiments | `search_experiments` |
| Scenarios that show web layers | `search_scenarios`, `search_scenario_nodes` (via `search_tools` and `call_tool`) |
| Performance (optional) | `get_event_schema`, `estimate_eql_cost`, `execute_analytics_eql` |
| Discovery placements (optional) | `get_discovery_weblayer_customizations` |

If a tool isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. There's no separate "weblayer" tool in Engagement: web layers are **banners**. Only ever use read tools: `search_tools` also returns write tools; never call them.

### Rules for calling the tools

- **One call at a time.** Engagement allows about 3 requests per second per user. EQL is limited to about **one query every 3 seconds across the whole Engagement instance**. On HTTP 429, wait at least 5 seconds and retry; if it happens again, wait 20 seconds.
- **Some tools may be denied.** `search_in_app_messages` and `search_experiments` can return HTTP 403 ("access denied") depending on the account's permissions or the project's features. Record "not checked (no access)" and carry on. Don't treat it as "none exist".
- **Banner details are very large and contain code.** Each variant holds full HTML, CSS and JavaScript (often tens of kilobytes). Never paste it into the answer. If the client saves a response to a file, extract only the fields listed in step 3, or run [scripts/audit_experiences.py](scripts/audit_experiences.py), which drops the content.
- **Never repeat content or personal data.** Variant HTML, scripts and parameters can contain internal IDs, URLs, prices and sometimes email addresses. Describe an experience by its name, type, placement and audience only.
- **Aggregate only.** Never call `list_customers`, `get_customer_properties` or `list_customer_events`.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/audit_experiences.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the project

If the user named a project, use it. Otherwise call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and **ask which one to use**. Never guess.

### 2. List everything

Make these calls one at a time:

1. `search_banners` with `archived=null` (live and archived together). Each record has `_id`, `name`, `status` (`active` or `inactive` only: **banners have no draft status**), `archived`, `tags`, `initiative_id`, and `created`/`edited` Unix timestamps. Use `limit` and `offset` if there are more than 200.
2. `search_banners` with `serving_status="serving"`, then with `"after_schedule"` and `"before_schedule"`. These filters are computed from the schedule, and are the cheapest way to find active banners that have **passed their end date** (`after_schedule`).
3. `search_in_app_messages`, `search_surveys` and `search_experiments` (lists). Record a 403 as "not checked".
4. Optionally, `search_scenarios` with `status="active"`, then `search_scenario_nodes` for scenarios that may show web layers: a node of type `serve-banner-action` shows a web layer from inside a flow, which the banner list doesn't reveal.

### 3. Fetch the details of the experiences that matter

Fetch by ID (`banner_id`, `message_id`, `survey_id`, `experiment_id`), one at a time:

- every **active** experience;
- **inactive** ones only if the user wants a full inventory (there can be dozens; the list alone is enough for clutter checks).

From each detail, keep only:

| Field | Meaning |
|---|---|
| `status`, `archived`, `edited` | State and staleness |
| `date_filter` (if present) | Schedule: `enabled`, `from_date`, `to_date`. **No `date_filter`, or `enabled: false`, means no end date** |
| `trigger.include_pages`, `trigger.exclude_pages` | Where it shows: `{"type": "any"}` means every page; otherwise URL rules such as `{"type": "contains", "url": "/p/"}` |
| `customer_filter` | Who sees it. `null` means **everyone** |
| `variants[]`: `name`, `enabled`, `percentage`, `type`, `is_embedded` | A/B split, format (for example a pop-up or an embedded block) |
| `variants[].parametrized_parts` / `html` / `script` / `style` | **Content: drop it, never show it** |

If you can run Python, save the list and detail responses to files and run:

```bash
python3 <this skill's folder>/scripts/audit_experiences.py banners_list.json banner_detail_*.json
```

It prints the findings for steps 4–6 without any content. It also accepts in-app message, survey and experiment responses.

### 4. Apply the checks

Read [references/audit-checks.md](references/audit-checks.md) for the full rules and severities. In short:

- **Expired but active:** active, and `to_date` is in the past (or it appears under `serving_status="after_schedule"`). **Action.**
- **Active, no end date:** active with no schedule. **Review** (fine for always-on experiences such as a chat widget; not for promotions).
- **Overlap:** two or more active experiences whose page rules overlap (either is "any page", or one URL rule contains the other) **and** whose audiences overlap (either has no customer filter, or both use the same filter). Treat pop-ups and overlays on the same pages as **Action**; embedded blocks in different slots as **Info**.
- **Never A/B tested:** one enabled variant at 100%, no control group. **Test.** Some web layers split traffic inside their own script; if the name or tags suggest a test, say "may split in code; confirm".
- **Drafts and clutter:** inactive and not edited for 90+ days; names containing draft, test, testing, copy, old, backup, dev, POC, QA, "do not use"; archived-looking names (for example "[ARCHIVED]") that aren't actually archived. **Cleanup.**
- **Poor results:** see step 5.

### 5. Check performance (only where it's tracked)

1. Call `get_event_schema` and check for a `banner` event (usual properties: `action`, `banner_id`, `banner_name`, `variant_id`, `variant_name`). Also note any custom event the web layers send (some track their own, for example a widget-specific event with `banner_id`).
2. Follow [references/eql-patterns.md](references/eql-patterns.md). Event-level breakdowns of `banner` events are usually rated `very_high` beyond 7 days on real projects, so the skill uses **customer counts** per banner and action instead.
3. Estimate every query. Run `high` only with the user's agreement; never run `very_high`.
4. If the active experiences have **no** banner events in the window, say so. It usually means the web layer tracks a custom event instead, or isn't firing. Don't call it a poor performer.

Flag as **poor** (Review): click-through (unique clickers ÷ unique viewers) below about 1% for a pop-up, or a close rate above about 60%. These are rough benchmarks; compare against the project's own median where you can.

### 6. Discovery placements (optional)

If the project also uses Bloomreach Discovery and an experience is placed through Discovery (for example a web layer shown for certain searches), `get_discovery_weblayer_customizations` with the `weblayer_id` lists the Discovery customizations and queries that reference it. Use it to explain **where** a web layer appears in search, and to avoid recommending the removal of one that Discovery still uses.

### 7. Prioritise

Order the findings: **Action** (expired-but-active, clashing overlaps) → **Test** (high-traffic experiences never tested) → **Review** (no end date, poor results) → **Cleanup** (drafts and clutter, grouped, not listed one by one if there are more than 10).

For each, say **what to do** and **who usually does it**: the marketer who owns the campaign, or the web team for code-heavy web layers.

## Output

```
## On-site experience audit: <project>, <date>

**Verdict:** <one sentence: the most important problem and the size of the clutter>

**Inventory:** web layers <active>/<total> (<archived> archived); in-app messages <n or "not checked (no access)">; surveys <n>; experiments <n or "not checked">

### Fix now
| Experience | Type | Problem | Evidence | Do this |
|---|---|---|---|---|

### Test next
| Experience | Placement | Why test | Suggested test |
|---|---|---|---|

### Review
- <active with no end date / poor results / possible overlaps>

### Clean up
- <n> inactive web layers not edited for 90+ days, mostly <naming pattern>: archive them
- <test and draft copies>

**Performance:** <banner events found or not; what was measured; queries skipped as very_high>
**Not checked:** <tools denied, scenario-served web layers not inspected, etc.>
```

Never include web layer HTML, scripts, parameters or customer-level data.

## Safety

This skill is **read-only**. It never activates, deactivates, edits, archives or deletes anything. If the user wants to act on the list, tell them to do it in the Engagement UI, and to check first whether a scenario or Discovery placement still uses the experience.
