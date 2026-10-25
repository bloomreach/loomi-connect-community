---
name: scenario-qa
description: Pre-launch QA for one Bloomreach Engagement scenario (journey, automation, flow) using Loomi Connect. Checks every email, SMS/MMS and mobile push step for broken links, Jinja personalization errors, compliance gaps (unsubscribe, postal address, STOP/HELP, consent, US SMS quiet hours and state rules, Canada CASL), deliverability and spam risk, then checks the flow for dead ends, orphans and unresolved references, and returns a severity-ranked GO / NO-GO report. Use when the user asks to QA, check, test, review or proof a scenario or journey before launch, or asks whether a flow is ready to go live.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement). Live link checks need a client that can make web requests.
metadata:
  author: jeffbird13-bloomreach
  version: "1.2.0"
  products: engagement
  access: read-only
---

# Scenario QA

## What this does

Audits one Bloomreach Engagement scenario before it goes live. It walks every step, checks each send by channel (links, Jinja, compliance, deliverability, content risk), checks the whole flow for structural problems, and returns a report a CRM or email marketer can act on in minutes: a GO / GO WITH CAUTION / NO-GO verdict, a triage table, and a paste-ready fix for each issue.

To explain what a scenario does, or to audit every scenario in a project for stale drafts and broken references, use `engagement-scenario-explainer` instead. This skill goes deep on one scenario's content before launch.

## Safety

This skill is **read-only**. It never creates, changes, starts, sends, test-sends or deletes anything in Bloomreach. Use only Loomi Connect read tools (`list_*`, `search_*`, `get_*`). Never call `create_*`, `update_*`, `clone_*`, `delete_*`, `start_*`, or any send or test-send tool. When something needs fixing, the report says what to change and the user makes the change.

Protect personal data in everything you show the user:

- Refer to sample profiles as "Profile A (rich data)", "Profile B (sparse)" and so on. Never show their customer IDs, email addresses, phone numbers or names. Sandbox projects can hold real customer data.
- When you show rendered Jinja, mask personal values (for example `Hi J***,`).
- Never repeat editor names or email addresses from scenario records, or webhook headers and payloads, which often hold API tokens.

## Before you start

You need:

| Input | Required | Notes |
|---|---|---|
| Project | yes | Confirm it on every run. Don't reuse one from an earlier run. |
| Scenario | yes | Name or ID. Resolve names to IDs. |
| Sample customers | no | Test profiles the user trusts for Jinja rendering. Chosen automatically if not given. |
| Vertical | no | Ask only if the scenario sends SMS and the industry is unclear. Regulated industries get stricter SMS checks. |
| Recipient locations | no | Countries and US states the scenario can reach. Read them from the scenario's filters first; ask only if the scenario sends SMS or may reach Canada and nothing limits the audience. Drives the North America checks. |

If a name matches nothing or more than one item, stop and ask. List the candidates with their IDs.

Loomi Connect tools this skill uses:

| Tool | Use |
|---|---|
| `list_cloud_organizations`, `list_projects` | Resolve the project |
| `search_scenarios` | List scenarios, resolve the name, read the definition (designs only with `include_node_designs=true`) |
| `search_scenario_nodes`* | Read one step's design at a time |
| `get_event_schema`, `get_customer_property_schema`, `get_mapping` | Check that referenced events and properties exist |
| `search_aggregates`, `search_catalogs`, `search_recommendations` | Check that referenced assets exist |
| `get_consent_settings`* | Check consent categories |
| `list_customers`, `get_customer_properties`, `list_customer_events` | Sample profiles for Jinja rendering |

\* If a tool isn't listed in the client, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`.

Make Loomi Connect calls one at a time. Organisation and project lookups allow about 1 request per second; other Engagement tools about 3. If a call returns HTTP 429, wait (use Retry-After if given) and retry.

## Steps

Print a short banner before each step, for example `━━━ STEP 1 / DISCOVERY ━━━`.

### Step 0: Confirm the target

1. Call `list_cloud_organizations`, then `list_projects` for each organisation.
2. If there's more than one project, list them and ask the user which to use. Never guess.
3. Call `search_scenarios` with the `project_id` to resolve the scenario name to an ID.
4. Confirm back: "QA'ing scenario `<scenario name>` (`<id>`) in project `<project name>`. Read-only." Then carry on.

### Step 1: Discovery (cheap structural pass)

1. Call `search_scenarios` with `scenario_id` and `include_node_designs=false`. This returns every node and the `connections` without the heavy designs.
2. Build a node table: id, type, name, channel, consent category, frequency policy, outgoing connections.
3. Read `connections` as `{"source": {"node_id", "connector_index"}, "destination": {"node_id", "connector_index"}}`. Output numbering:
   - The trigger is a node (the top-level `trigger` field is `null`). Its output is `0`.
   - `condition`: output `1` = matches, `2` = doesn't match.
   - `ab-split`: one output per variant, numbered by the variant's `id`, not its position. Ids can have gaps. `ab-split-contextual` numbers variants from `0` and their outputs from `id + 1`.
   - `wait`: output `1`. `limit`: `1` = within the limit, `2` = over it. Actions: `1` = success, `2` = failure.
   - Node fields sit at the top level of each node (`event`, `customer_filter`, ...), not under `config`.
4. Collect every event, property, aggregate, catalog and recommendation referenced by the trigger, conditions and sends.
5. Call `get_event_schema` and `get_customer_property_schema` and check every reference resolves. These responses are large; keep only what you need.
6. If the scenario has more than about 25 sends, tell the user the run will take longer before continuing.
7. **Work out where recipients are** if the scenario sends SMS or MMS, or may reach Canada. Follow "Where recipients are" in the "SMS and MMS: North America" section of [references/check-catalog.md](references/check-catalog.md). State the result at the top of the report, for example "Audience: all US states plus Canada (no location filter; assumed)".

### Step 2: Check each send

For each send step, fetch its design only now, one step at a time: `search_scenario_nodes` with `scenario_id`, `node_id` and `include_design: true`, or `search_scenarios` with `include_node_designs=true` for small scenarios. Designs can exceed 70 KB per step. If the client saves a large result to a file, extract the fields you need with a short script instead of reading the whole file.

Run the channel checks in [references/check-catalog.md](references/check-catalog.md):

| Area | Email | SMS / MMS | Push |
|---|---|---|---|
| Links | ✔ | ✔ | deep link and web fallback |
| Jinja render against sample profiles | ✔ | ✔ | ✔ |
| Compliance | CAN-SPAM, CASL (Canada) | STOP/HELP, consent, brand ID, US quiet hours and state rules, CASL (Canada), Texas SB 140 | consent category |
| Deliverability / rendering | subject, preheader, alt text, size, dark mode | segments, length | title and body length |
| Spam / content risk | spam heuristics | prohibited content | — |
| Configuration | sender, consent, frequency policy | sender, shortener, consent | consent, frequency |

**Links.** Work through every link in two passes. The full rules are in the Links section of [references/check-catalog.md](references/check-catalog.md).

1. **Static checks first (no web access needed).** Look for missing schemes, `http://`, placeholder words in the path and near-miss hosts. These catch some broken links even when nothing can be loaded.
2. **Then load each link, trying every method this client offers, in order:**
   1. A web-fetch tool, if there is one.
   2. If that tool is missing, or refuses the URL (for example "not on allowlist" or a blocked domain), a browser tool if the client has one: for example Claude in Chrome, the built-in browser in the Claude desktop app, or another client's browser tool. Open each link in a new tab and read the real HTTP status with a one-line script where the tool allows it. Check other links on the same host from that page. Never click, sign in, solve a CAPTCHA or submit anything.
   3. Only when no method can load a link, mark it **not checked**.

   A tool that refuses one domain doesn't prove the others will fail, so keep trying the next method for each link.

**Unchecked links are findings, not footnotes.** Every primary call-to-action or hero link that couldn't be checked gets its own **warning** row in the triage table ("Not checked: click before launch"). Group the remaining unchecked links into one warning row. Never leave an unchecked primary link only in "couldn't verify".

**Sample profiles.** Use the user's test profiles first. Otherwise call `list_customers` **with a query and a small `count`** (without a query it returns every customer), and pick 3–5 profiles with varying data completeness: one rich, one sparse, one missing key attributes.

### Step 3: Check the whole flow

Run the flow-level checks in [references/check-catalog.md](references/check-catalog.md): orphans, dead ends, unreachable branches, unresolved or archived references, missing exit or suppression logic, waits and time zones, re-entry, A/B split totals.

### Step 4: Report

Return the report in the format below. If the user wants to share it, offer to turn it into a document.

## Severity and verdict

- **Blocker**: must be fixed before launch. Any blocker means **NO-GO**.
- **Warning**: should be fixed; launching is a judgement call. Warnings only means **GO WITH CAUTION**.
- **Nitpick**: polish. Nitpicks only means **GO**.

Counts include issues on individual steps and flow-level issues.

If any link couldn't be checked, the best possible verdict is **GO WITH CAUTION**, even with no other issues: an unchecked link can't earn a clean GO.

## Output

Write for a CRM or email marketer: verdict first, then a table to scan, then detail. Use placeholders only in this template; the real report shows only data from the scenario under test.

**1. Verdict banner (one line)**

```
🔴 NO-GO — <scenario name> · 1 blocker · 2 warnings · 0 nitpicks · Channels: Email, MMS
```

Use 🟢 GO, 🟡 GO WITH CAUTION or 🔴 NO-GO. When links couldn't be checked, add the count to the banner, for example `· 3 links not checked`.

**2. Triage table (most severe first)**

| # | Severity | Channel | Step | Issue | Fix |
|---|---|---|---|---|---|
| 1 | 🔴 Blocker | SMS | node 9 "<node name>" | No opt-out language | Append "Reply STOP to opt out" |
| 2 | 🟡 Warning | Email | node 13 "<node name>" | Preheader empty | Add a 40–90 character preheader |

Identify steps by their numeric node ID plus name.

**3. Issue detail (one block per issue)**

```
[BLOCKER] SMS · node 9 "<node name>"
Checked:  marketing SMS opt-out language
Found:    no STOP or opt-out text anywhere in the rendered body
Where:    message body
Fix:      paste-ready corrected body:
          {{ brand_name }}: … Shop now! Reply STOP to opt out.
```

Give corrected, paste-ready text wherever you can.

**4. Flow-level issues**

A separate section in plain words, for example: "The 'Viewed category?' branch ends in a 4-hour wait with nothing after it."

**5. Passed checks and couldn't verify**

A short list of what passed, so the reader can trust the clean areas, and every link or reference you couldn't verify, with the reason.

## Common pitfalls

| Pitfall | Do instead |
|---|---|
| Fetching every design in step 1 | Structure first; designs one step at a time in step 2 |
| Calling a 403 or bot-blocked link "broken" | Report it as "not checked" |
| Giving up on links after the web-fetch tool refuses a domain | Try the browser tool next, link by link |
| Leaving an unchecked call-to-action at the bottom of the report | Give it a warning row in the triage table |
| Trusting a link because it looks normal | Load it: a valid-looking URL can still 404 |
| Checking a URL with unrendered Jinja | Render it against a sample profile first |
| Flagging an A/B holdout group as a dead end | It's intentional; note it only |
| Reusing a project from an earlier run | Confirm the project every time |
| Firing lookups in parallel and hitting 429s | One call at a time |
| Reading a huge saved result in full | Extract the fields you need with a script |
| Showing a sample customer's real details | Mask them; label profiles A, B, C |
| Making any change in Bloomreach | Never; report the fix and let the user apply it |
