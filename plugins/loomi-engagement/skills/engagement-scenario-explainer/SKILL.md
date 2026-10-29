---
name: engagement-scenario-explainer
description: Explains a Bloomreach Engagement scenario (automation flow) in plain English, covering its trigger, who enters, conditions, waits, A/B splits, actions and channels, using Loomi Connect. Also audits all scenarios in a project for stale drafts, broken or missing references to segments, templates or consent categories, disconnected nodes and inactive flows. Use when the user asks what a scenario or automation does, how a flow works, who gets a journey, or wants a scenario audit or clean-up list.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement).
metadata:
  author: bloomreach
  version: "0.2.4"
  products: engagement
  access: read-only
---

# Engagement scenario explainer

## What this does

Two modes:

- **Explain:** takes one scenario and describes it in plain English: how customers enter, who qualifies, what happens to them step by step, which channels it uses, and anything that looks wrong.
- **Audit:** looks at every scenario in a project and lists the ones that are stale, inactive, disconnected or that point at objects that no longer exist, with a suggested action for each.

This skill only reads. It never starts, stops, edits or deletes a scenario.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Project | `list_cloud_organizations`, `list_projects` |
| Scenarios | `search_scenarios`, `search_scenario_nodes` (not listed by default: find it with `search_tools`, run it with `call_tool`) |
| Referenced objects | `search_segmentations`, `search_customer_filters`, `search_aggregates`, `search_expressions`, `search_predictions`, `search_email_campaigns`, `search_sms_campaigns` |
| Templates and consent | `search_email_assets`, `get_consent_settings` (both via `search_tools` and `call_tool` if not listed) |
| Run activity (optional) | `estimate_eql_cost`, `execute_analytics_eql` |

If a tool isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Only ever use read tools: `search_tools` also returns write tools; never call them.

### Rules for calling the tools

- **One call at a time.** Engagement allows about 3 requests per second per user, and analytics (EQL) queries have their own, stricter limit of roughly one query every 3 seconds. On HTTP 429, wait a few seconds and retry once.
- **Large responses.** A full scenario can be large, especially webhook and email nodes. If the client saves a response to a file, extract only what you need. [scripts/scenario_graph.py](scripts/scenario_graph.py) reads a saved `search_scenarios` detail response and prints the triggers, the flow outline, the references and the structural warnings.
- **Never repeat sensitive node content.** Webhook bodies, headers and URLs can hold email addresses, tokens or internal endpoints. Describe what a webhook does ("posts a JSON event to an external tracking API"), never paste its payload.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/scenario_graph.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the project

If the user gave a project name or ID, use it. Otherwise call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and ask which one to use. Never pick one yourself.

### 2. Find the scenario (explain mode)

Call `search_scenarios` with the `project_id` and no `scenario_id`. The list gives each scenario's `_id`, `name`, `status` (`draft`, `active`, `inactive`, `paused`), `tags`, `initiative_id`, and `created`/`edited` Unix timestamps. It does **not** include triggers, nodes or run history.

Match the user's wording to a name. If several match, list them with status and last-edited date and ask. Archived scenarios are hidden by default; pass `archived=true` only if the user asks about one.

### 3. Get the flow

1. Call `search_scenario_nodes` (via `call_tool`) with `project_id` and `scenario_id`. This returns a light **graph map**: each node's `id`, `type` and `name`, with its incoming and outgoing connections.
2. Then get the configuration. Either call `search_scenarios` with the `scenario_id` (all nodes at once; email and SMS designs are stripped by default), or call `search_scenario_nodes` with a `node_id` for each node you need. Use per-node calls for big scenarios.

Points to know:

- The top-level `trigger` field is usually `null`. **Triggers are nodes** whose type ends in `-trigger`. A scenario can have several triggers, each starting its own path.
- A `now-trigger` with `"active": false` is the manual "run now" entry point and isn't firing on a schedule.
- `label` nodes are notes the author left on the canvas. Read them: they often state the scenario's purpose, and they're the best source for the explanation.
- On a `condition` node, output connector `1` is "matches" and `2` is "doesn't match". On an `ab-split`, each output is numbered by its variant's `id` (ids can have gaps, such as `1`, `2`, `4`); on an `ab-split-contextual`, by `id + 1`. On a `limit`, `1` is within the limit and `2` is over it.

See [references/node-types.md](references/node-types.md) for what each node type means and which fields to read.

### 4. Resolve what the nodes reference

Collect the IDs that nodes point at, then look each one up once (one call at a time, reusing list responses):

| Where it appears | What it is | Look it up with |
|---|---|---|
| `customer_filter.filters[].attribute` with `type: "segmentation"` and an `id` | A segmentation used as a condition | `search_segmentations` (list, then match `_id`) |
| same, with `type` `aggregate`, `expression` or `prediction` | A computed attribute | `search_aggregates`, `search_expressions`, `search_predictions` |
| `customer_filter.filters[]` with `type: "funnel_steps"` | An event-history condition | Read it directly: event name, property filters, date window |
| `template_id` on an action node | A saved template | `search_email_assets` (via `call_tool`); `null` means the design is inline in the node, which is normal |
| `consent_category` on an action node | A consent category | `get_consent_settings` (via `call_tool`): check the ID is in `categories` |
| `metrics("<id>")` or `report_value_by_key("<id>")` in Jinja | A saved metric or report | Name it as "a saved metric"; don't guess what it measures |

**Useful shortcut:** in the `search_segmentations` list, each segmentation's `used_by` includes `campaign_design_<scenario_id>` for every scenario that uses it. That gives you the segments a scenario depends on without opening every node.

Only call a reference **missing** when you looked in the right list and it isn't there. IDs inside `limit` nodes and similar may point at objects there's no read tool for. Report those as "not verified" instead.

### 5. Explain it

Walk the flow from each trigger along the connections, and describe it as a story a marketer would follow:

1. **Purpose:** one sentence, from the name, labels and actions.
2. **Entry:** the trigger in plain words ("every day at 18:00 New York time", "when a customer tracks `cart_update`", "on each customer's `birthday` date").
3. **Who qualifies:** the conditions on the path, using segment and property names, not IDs.
4. **What happens:** waits, splits (with percentages), limits and actions, in order. Name the channel for each action (email, SMS, push, webhook, in-app, property update, event tracking).
5. **Channels and consent:** which consent category each message uses, and whether `general_consent` is on.
6. **Things to check:** see the structural checks in [references/audit-checks.md](references/audit-checks.md).

Optional: estimate how many customers currently qualify for the entry condition with an aggregate EQL count. Use the `engagement-segment-builder` skill's method if it's installed (its "Sizing an existing customer filter" section translates a condition). Conditions that use segments, predictions or aggregates can't be counted this way. For each step's results, hand off to `engagement-scenario-performance`. Always run `estimate_eql_cost` first.

### 6. Audit mode

When the user asks for an audit, clean-up or health check of scenarios:

1. List live scenarios with `search_scenarios` (page with `limit` and `offset` if there are more than 200). Also check `archived_items_exists`.
2. Classify each scenario from list data alone: status, days since `edited`, and whether it's tagged or in an initiative.
3. For scenarios that are **active** or were **edited in the last 180 days**, fetch the graph map and run the structural checks. For large projects, ask the user before opening more than about 20 scenarios, because each one is at least one call.
4. Fetch the segmentation list **once**, and use it for every reference check and for the `used_by` shortcut.
5. Run activity is optional. It needs EQL over the `campaign` event, which is costly on large projects. See [references/audit-checks.md](references/audit-checks.md) for the query, and only run it if `estimate_eql_cost` says `low` or `medium`, or the user agrees to a `high` one. Never run `very_high`. If you skip it, say that "last run" wasn't checked.

Apply the checks and severity levels in [references/audit-checks.md](references/audit-checks.md).

For pre-launch QA of one flow, use `scenario-qa`. For project-wide hygiene across all asset types, use `engagement-asset-cleanup`.

## Output

### Explain mode

```
## Scenario: <name> (<status>, last edited <date>)

**In one sentence:** <what it does and for whom>

**How customers enter:** <trigger(s), in plain words>
**Who qualifies:** <conditions, using names>
**What happens:**
1. <step>
2. <step>
**Channels:** <email / SMS / webhook / ...>, consent: <category or "general consent">

**Things to check:**
- <structural warnings, broken references, or "None found">

**Not verified:** <references there's no read tool for, if any>
```

Keep it under about 30 lines. Offer to go into any node in detail.

### Audit mode

```
## Scenario audit: <project> (<n> live scenarios, <date>)

| Scenario | Status | Last edited | Finding | Severity | Suggested action |
|---|---|---|---|---|---|

**Summary:** <n> need action, <n> to review, <n> look healthy.
**Not checked:** <e.g. run activity, scenarios beyond the first 20>
```

Sort by severity, then by last-edited date (oldest first).

## Safety

This skill is **read-only**. It never creates, edits, starts, stops, archives or deletes a scenario or anything it references.

- Recommend actions, such as "archive this draft" or "reconnect node 12", for the user to take in the Engagement UI. Don't call `update_scenario`, `update_scenario_node`, `delete_scenario` or any other write tool, even if asked. Running scenarios can only be changed in the UI anyway.
- Don't read individual customer records. Use aggregate counts only.
- Don't repeat personal data, credentials, tokens or webhook payloads found in node configuration.
