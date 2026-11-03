---
name: engagement-send-collision-check
description: Checks the Bloomreach Engagement campaign calendar and scenarios for overlapping email and SMS sends to the same or overlapping audiences within a date window, using Loomi Connect, and flags over-messaging risks, busy days, email and SMS channel conflicts, and missing frequency caps. Use when the user asks whether campaigns clash or overlap, if customers are getting too many messages, to check the send schedule or campaign calendar for a week, or before launching a campaign.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement).
metadata:
  author: bloomreach
  version: "0.1.4"
  products: engagement
  access: read-only
---

# Engagement send collision check

## What this does

Looks at what is scheduled to send in a window (default: the next 14 days), works out who each send targets, and flags:

- **collisions**: two sends that reach the same or overlapping audiences too close together;
- **busy days**: days with many more sends than usual;
- **channel conflicts**: email and SMS to the same people on the same day;
- **missing protection**: sends that use an unlimited frequency policy, so nothing caps how many messages a customer gets.

It reads campaign and scenario definitions only. It never changes anything, and never reads individual customers.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Project | `list_cloud_organizations`, `list_projects` |
| Schedule | `get_campaign_calendar` |
| Definitions and audiences | `search_scenarios`, `search_scenario_nodes`, `search_email_campaigns`, `search_sms_campaigns`, `search_segmentations` |
| Frequency caps | `get_frequency_policies` |

`search_scenario_nodes` and `get_frequency_policies` may not be listed directly. Find them with the Loomi Connect `search_tools` tool and run them with `call_tool`. Use read tools only: `search_tools` also returns write tools; never call them.

Ask the user for the window if they didn't give one, and for the project's timezone if they want local times (calendar times are UTC Unix timestamps).

### Rules for calling the tools

- **One call at a time.** Engagement allows about 3 requests per second per user. On HTTP 429, wait 3–5 seconds and retry.
- **Keep responses small.** Prefer `search_scenario_nodes` (graph map, then single nodes) to a full `search_scenarios` detail call: full scenarios can contain large templates. Never pass `include_design` or `include_node_designs`. `search_segmentations` and `get_frequency_policies` responses can exceed 50,000 characters; if the client saves them to a file, extract only the fields named below.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/find_collisions.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the project

Call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and ask the user which to use. Never guess.

### 2. Read the calendar

Call `get_campaign_calendar` with `from_ts` and `to_ts` for **one week at a time**. Wide windows can time out (`error='timeout'`); if one does, halve the window. Merge the weeks.

Each entry is one send **action**, not one campaign. A scenario with an email node and an SMS node appears twice, under the same `campaign_id`. Useful fields: `campaign_id`, `campaign_name`, `action_name`, `channel`, `status`, `trigger`, `times[].start` (UTC seconds), `results.reach`, `results.potential_reach`.

Know what the calendar does and doesn't show:

- It includes **draft and inactive** scenarios, with their planned times. Leave them out of the collision count, but list them under "Planned but not active" so the user knows they would clash if switched on.
- It includes **webhook** and other non-message actions. Leave them out unless the user asks.
- It **does not** include event-triggered sends (welcome, abandoned cart, post-purchase). Step 3 finds them.

### 3. Find always-on flows

Call `search_scenarios` with `status="active"` and `trigger_types=["onevent", "ondateattribute", "onapi", "onapi-interest", "oncatalog"]`. These run continuously, so they add load on top of anything scheduled. For each one that sends email or SMS (check with step 4), list it as **background load** with its trigger. Don't try to predict exact times.

### 4. Work out each send's audience

For each distinct `campaign_id` left after step 2 (and each flow from step 3). For node types and filter shapes, read [references/scenario-audiences.md](references/scenario-audiences.md).

1. **Scenario.** Call `search_scenario_nodes` with no `node_id` to get the graph map. Find the send nodes (`send-email-action`, `send-sms-action`, `send-mms-action`, push actions) and walk back through `incoming_connections` to the trigger. For each `condition` or `segmentation-fork` node on that path, fetch it with `node_id` and read its `customer_filter`:
   - a filter whose `attribute.type` is `"segmentation"` targets a segment: note `attribute.id` (the segmentation) and the operand value (the segment name; `has value` means "in any segment");
   - other filters are inline conditions: summarise them in a few words, for example "purchased in last 90 days";
   - no conditions on the path means **everyone** the trigger reaches.
   Also note any `limit` nodes, and the send node's `frequency_policy` (fetch the send node itself; its design is excluded by default).
2. **Standalone email campaign.** Call `search_email_campaigns` with `campaign_id` (keep `include_design` false) and read the customer filter and frequency policy.
3. **Standalone SMS campaign.** `search_sms_campaigns` list mode includes the customer filter. HTTP 403 usually means SMS isn't enabled for the project; note it and carry on.
4. **Cross-check with segmentations.** Call `search_segmentations` (list mode) once. Each segmentation's `used_by` list contains entries like `campaign_design_<id>`, where `<id>` is a scenario or campaign ID. Use it to confirm which sends share a segmentation, and to find any you missed.

Compare audiences with these rules:

| The two sends target | Verdict |
|---|---|
| Either has no filter (everyone) | Overlap |
| The same segment of the same segmentation | Same audience |
| Different segments of the same segmentation | No overlap: a customer is in only one segment of a segmentation |
| Different segmentations, or inline filters | Possible overlap: say what each targets and let the user judge |

Don't measure the overlap by listing customers. If the user needs a size, offer an aggregate EQL count, run `estimate_eql_cost` first, and warn that it is expensive on large projects.

### 5. Check frequency caps

Call `get_frequency_policies` once. Read only each policy's `id`, `name`, `segments[].name` and `segments[].rules` (limit per duration), plus `default_policy_id`. Ignore the `customer_filter` blobs. Flag:

- any send in a collision that uses `unlimited-policy`;
- a project whose `default_policy_id` is `unlimited-policy`, because sends that don't set a policy then have no cap.

A frequency policy stops a customer receiving too many messages, but the later send is the one that gets dropped. A collision under a strict policy can therefore mean a key campaign silently misses people.

### 6. Find collisions and busy days

Save each calendar response as JSON (give several files, one per week, and the script merges them), and the audiences from step 4 as a small JSON map, then run:

```
python3 <this skill's folder>/scripts/find_collisions.py calendar_week1.json calendar_week2.json --audiences audiences.json --utc-offset <hours>
```

The script's docstring describes the audience file. By default it flags:

- the same channel to overlapping audiences within **24 hours**;
- email and SMS to overlapping audiences within **4 hours**;
- busy days with **3 or more** sends, or twice the median for the window;
- SMS scheduled outside **08:00–21:00** local time.

Change the thresholds with `--same-channel-hours`, `--cross-channel-hours` and `--busy-day` if the user has their own rules. If you can't run scripts, apply the same rules by hand.

The script prints each send's `results.reach` (or `potential_reach`) and lists the largest combined reach first. Weigh each collision by it: a clash between two sends of 50,000 matters more than one between two sends of 200.

## Output

```
## Send collision check: <project>, <window> (<timezone>)

**Verdict:** <one sentence, e.g. "2 likely collisions, both on Tuesday 22nd; the project has no default frequency cap">

| Day | Sends | Email | SMS | Flag |
|---|---|---|---|---|
| ... |

### Collisions
1. **<send A> → <send B>**: <gap> apart, <channel(s)>, <verdict: same audience / overlap / possible overlap>. Audience: <A's target> vs <B's target>. Reach: <n> / <n>. Cap: <policy>. Suggest: <move B to <day>, exclude A's recipients, or merge>.

**Background load (always-on flows):** <name: trigger, channel>, ...
**Planned but not active:** <draft or inactive sends that would clash if switched on>
**Frequency caps:** <default policy; any sends on unlimited>
**Not checked:** <anything you couldn't see, e.g. SMS not enabled, inline filters you couldn't compare>
```

Keep it under about 35 lines. Rank collisions by combined reach. Offer to look at a specific day or campaign in more detail.

## Safety

This skill is **read-only**. It never creates, changes, reschedules, pauses or deletes campaigns, scenarios, segmentations or policies. If the user wants to move a send, describe the change for them to make in Engagement.

- Never call `list_customers`, `get_customer_properties`, `list_customer_events` or `list_customers_in_segment`.
- Scenario nodes, especially webhooks, can contain email addresses or other personal data in templates. Don't repeat them.
