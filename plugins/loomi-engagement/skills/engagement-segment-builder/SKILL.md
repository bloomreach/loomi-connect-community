---
name: engagement-segment-builder
description: Turns a plain-English audience description into a Bloomreach Engagement segment definition using Loomi Connect, for example "bought in the last 90 days but not the last 30, with email consent". It maps the words to real customer properties, events and consent categories, reuses existing segments where possible, estimates the audience size with an aggregate EQL count, and gives step-by-step build instructions. It can create the customer filter or segmentation after explicit confirmation. Use when the user wants to build, define, size or create a segment, audience or customer filter.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement).
metadata:
  author: bloomreach
  version: "0.3.0"
  products: engagement
  access: writes
---

# Engagement segment builder

## Safety

This skill **can write** to Bloomreach Engagement, but only when the user asks for it. The only things it can change:

- **create** one customer filter, with `create_customer_filter`; or
- **create** one segmentation, with `create_segmentation`.

It never updates or deletes existing filters or segmentations, and never creates or changes campaigns or scenarios. A new filter or segmentation doesn't affect any campaign until someone uses it.

Before any write: show the user the exact name and definition (the plain-English summary **and** the JSON payload), say which project it goes into, and wait for an explicit "yes". If they change anything, show it again and ask again. Never read individual customer records: sizing uses aggregate counts only.

## What this does

Takes an audience description in everyday words and returns:

1. the definition in plain English, in EQL and (when it can be built reliably) as an Engagement customer filter;
2. the existing segments and filters it reuses or overlaps with;
3. an estimate of the audience size;
4. step-by-step instructions to build it in the Engagement UI;
5. optionally, the created filter or segmentation, after confirmation.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Project | `list_cloud_organizations`, `list_projects` |
| Data model | `get_customer_property_schema`, `get_event_schema`, `get_customer_schema` (identifiers), `get_consent_settings` (via `search_tools` and `call_tool` if not listed) |
| Reuse | `search_segmentations`, `search_customer_filters`, `search_aggregates`, `search_predictions` |
| Sizing | `estimate_eql_cost`, then `execute_analytics_eql` |
| Writes (only after confirmation) | `create_customer_filter`, `create_segmentation` (not listed by default: find them with `search_tools`, run them with `call_tool`) |

If a tool isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`.

### Rules for calling the tools

- **One call at a time.** Engagement allows about 3 requests per second per user. Analytics (EQL) queries are limited separately to about one every 3 seconds, shared with other users of the same instance. On HTTP 429, wait 3–5 seconds and retry once.
- **Large responses.** `get_event_schema` and `search_segmentations` can be tens of kilobytes. If the client saves them to a file, extract only the names and types you need.
- **Never** call `list_customers`, `list_customers_in_segment`, `get_customer_properties` or `list_customer_events`. This skill describes audiences; it never looks at individual people.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/filter_to_eql.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the project

If the user gave a project name or ID, use it. Otherwise call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and ask which to use. Never pick one yourself. Suggest a sandbox project for trying things out, but build the definition in the project where it will be used.

### 2. Break the description into conditions

Split the request into separate conditions, each one of:

| Kind | Example wording |
|---|---|
| Event happened (optionally in a window, with property filters) | "bought in the last 90 days", "viewed a product over $100" |
| Event did **not** happen | "but not in the last 30 days", "never opened an email" |
| Event frequency | "bought at least twice this year" |
| Customer property | "in the US", "loyalty tier gold", "has a phone number" |
| Consent | "with email consent", "opted in to newsletters" |
| Existing segment | "VIPs", "in the churn-risk segment" |

Write down anything vague ("recently", "active", "high value") and ask the user what it means, or propose a default and say so ("I've taken 'recently' as the last 30 days").

### 3. Map words to the data model

1. Call `get_customer_property_schema`. Match properties by name and `type`. Prefer properties with `used: true`.
2. Call `get_event_schema`. Use each event's `type` as its name, and its `properties.default_group.properties` for event-property filters. A purchase event is usually `purchase`, but check: some projects use custom names, or have an item-level event such as `purchase_item` as well.
3. For consent, call `get_consent_settings` (via `call_tool`) and use the `id` of the matching entry in `categories`. Also check whether the project tracks a `consent` event in `get_event_schema`. If the category doesn't exist, or there's no consent data, **say so**. Don't swap in a lookalike (such as "has an email address") without labelling it clearly as **not** consent.
4. If two candidates fit equally well (for example `country` and `country_code`), ask.

Never invent a name. The EQL cost estimator does **not** check that properties or events exist, so a typo only shows up as a wrong count.

### 4. Look for something to reuse

1. List `search_segmentations` and `search_customer_filters`. Look for names that match the whole audience or one of its parts ("lapsed", "consent", "VIP").
2. Fetch the one or two best candidates by ID, and read their definitions.
3. Then either:
   - **exact match:** recommend reusing it, and stop unless the user still wants a new one;
   - **matching part:** build on it (an existing segmentation can be one condition of the new definition);
   - **overlap:** mention it, so the user doesn't end up with near-duplicates.
4. Also check `search_aggregates` and `search_predictions` when the wording suggests a computed value ("lifetime value", "churn risk"). Don't recompute what already exists.

### 5. Write the definition

Produce three forms:

- **Plain English:** one bullet per condition, joined with AND, OR or NOT, as the user would say it.
- **EQL:** a `customers matching` expression. See [references/eql-patterns.md](references/eql-patterns.md) for the tested patterns and syntax traps.
- **Customer filter JSON:** only when you can copy a real template atom for every kind of condition from the project. See [references/filter-definitions.md](references/filter-definitions.md). Otherwise say "build in the UI" and skip the JSON.

### 6. Estimate the size

1. Build a count query: `select count customers by customer.<low-cardinality property> grouping top 3 with null customers matching <conditions>`.
2. Call `estimate_eql_cost`.
   - `success: false`: fix the syntax using the parser message and estimate again.
   - `low` or `medium`: run it with `execute_analytics_eql`.
   - `high`: tell the user the rating and the `factors`, and run only if they agree. Large projects often rate even simple counts as high.
   - `very_high`: don't run it. Simplify, or give the definition without a size.
3. Add up **all** returned rows, including the `null` and "other" rows. An empty `rows` list means zero.
4. If it's zero or looks wrong, follow "When the count is zero or surprising" in [references/eql-patterns.md](references/eql-patterns.md). Find out whether it's a definition problem or just no recent data.
5. Round the number in your answer (for example "about 48,000") and give the time it was computed. Counts change as data arrives.

To size a filter that already exists, such as a saved customer filter or a condition in a scenario, save the tool result to a file in your working folder and translate it with the script:

```
python3 <this skill's folder>/scripts/filter_to_eql.py <saved filter, condition node or scenario>.json --with-total
```

For a whole `search_scenarios` response, add `--node <condition node id>`. It prints JSON with `eql` (the `customers matching` condition, or `null` when the filter lets everyone through), `unsupported` (what stops it being counted) and `query` (the count query). `--with-total` adds a second column that counts everyone, so you can give the audience as a share of all customers; `--by <property>` changes the breakdown property (default `country`); `--out <file>` writes the JSON to a file instead.

- If `unsupported` isn't empty (segments, predictions, aggregates, expressions, calculations, absolute date windows and other rules EQL can't express here), say which kinds of rule stop it and don't size the rest on its own: that would overstate the audience.
- Otherwise check `query` with `estimate_eql_cost` and run it only as in steps 2 to 5 above. Add up each column over **all** rows: the first is the audience, the second (with `--with-total`) is everyone.

If you can't run scripts, translate it by hand with "Sizing an existing customer filter" in [references/eql-patterns.md](references/eql-patterns.md), which gives the same rules.

Optional, and only if the user wants it: break the audience down by one more property, with `grouping top 10`. Estimate the cost again first.

### 7. Give build steps for the UI

Give numbered steps for building it in Bloomreach Engagement. Menu labels can vary slightly between versions.

1. Go to **Analyses → Segmentations → + Create new** (for buckets), or create a saved **customer filter** where your team keeps reusable filters.
2. Name it.
3. Add each condition:
   - customer property: choose **Customer attribute → property → operator → value**;
   - event: choose **Event → event name**, add property filters, and set the **date range** (for example "in the last 90 days");
   - "did not": add the event condition, then **negate** it;
   - consent: add the **consent** condition for the category;
   - existing segment: choose the **segmentation** attribute and the segment.
4. Combine them with AND or OR, as in the plain-English definition.
5. Save, then check the customer count the UI shows against the estimate.

### 8. Offer to create it (optional)

Only if the customer filter JSON was built from real templates (step 5):

1. Ask whether they want a **customer filter** (one reusable audience) or a **segmentation** (named buckets).
2. Show the exact payload from [references/filter-definitions.md](references/filter-definitions.md): project, name, `filters`, `formula`, and the segment names for a segmentation.
3. Wait for an explicit "yes". Then call `create_customer_filter` or `create_segmentation` through `call_tool`, once.
4. Report the returned `id`, or the `error` exactly as returned. Don't retry with guessed changes. Suggest opening it in the UI to check the count.

## Output

```
## Audience: <short name>

**Definition**
- <condition 1>
- AND <condition 2>
- AND NOT <condition 3>

**Mapped to:** <event `purchase`>, <property `country`>, <consent category `newsletter`>
**Reuses / overlaps:** <existing segment or filter, or "nothing similar found">

**Estimated size:** about <n> customers (as of <time>; EQL cost: <level>)

**EQL**
    customers matching ...

**Build it in the UI**
1. ...

**Assumptions and gaps:** <defaults chosen, missing consent data, conditions that can't be written via the API>

Want me to create this as a customer filter or segmentation in <project>? I'll show you the exact definition first.
```

Leave out the last line if the definition can't be written reliably through the API.
