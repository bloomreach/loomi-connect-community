---
name: funnel-leak-finder
description: Finds where revenue leaks between product view, add to cart, checkout and purchase in Bloomreach Engagement using Loomi Connect, with aggregate EQL funnel counts by step and by device or traffic source, abandoned-cart volume and value, and a check of whether cart abandonment, browse abandonment and post-purchase scenarios exist and are active. Returns the biggest leaks with the revenue at stake and the missing or weak recovery flows. Use when the user asks where shoppers drop off, why conversion is low, how much abandoned carts cost, for a funnel or checkout analysis, cart abandonment numbers, or whether recovery flows are in place.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Engagement). Python 3 is optional, for the bundled script.
metadata:
  author: bloomreach
  version: "0.1.4"
  products: engagement
  access: read-only
---

# Funnel leak finder

## What this does

Measures how many customers move from viewing a product to adding to cart, (where tracked) starting checkout, and buying, then puts a revenue figure on each drop-off. It also breaks the funnel down by device or traffic source where the data allows, sizes abandoned carts, and checks whether the flows that recover lost revenue exist and are running:

- **cart or checkout abandonment** (on `cart_update` or `checkout`);
- **browse abandonment** (on `view_item`);
- **post-purchase** (on `purchase`: thank-you, cross-sell, review request).

The answer is a short list of the biggest leaks, each with the revenue at stake and the next step, plus the missing or weak recovery flows, with hand-offs to `engagement-segment-builder` (to define the recovery audience) and `engagement-scenario-explainer` (to inspect an existing flow).

It uses aggregate counts only. It never reads individual customers and never changes anything. To see how an existing recovery flow performs step by step, use `engagement-scenario-performance`. For campaign results across a period, use `engagement-campaign-digest`.

## Before you start

This skill uses these Loomi Connect tools:

| Purpose | Tools |
|---|---|
| Project | `list_cloud_organizations`, `list_projects` |
| Data model | `get_event_schema` |
| Existing analyses | `search_funnels` |
| Counts | `estimate_eql_cost`, `execute_analytics_eql` |
| Recovery flows | `search_scenarios`, `search_scenario_nodes` (not listed by default: find it with `search_tools`, run it with `call_tool`) |

If a tool isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Only ever use read tools: `search_tools` also returns write tools; never call them.

Ask the user for the **window** (default: last 30 days) and the **conversion window** between steps (default: 7 days; use 1 day for fast-moving or low-price catalogs). Ask for a **recovery rate** assumption if they have one from their own flows; otherwise use the defaults in [references/revenue-at-stake.md](references/revenue-at-stake.md) and label them as assumptions.

### Rules for calling the tools

- **One call at a time.** Engagement allows about 3 requests per second per user. **EQL allows about one query every 3 seconds, and the limit is shared by everyone on the same Engagement instance**, so you may get HTTP 429 even when calling slowly. `estimate_eql_cost` counts towards the same limit. Wait 3–10 seconds between EQL calls, and on 429 wait and retry once.
- **Estimate every query first.** `low` or `medium`: run it. `high`: tell the user the rating and why, and run only with their agreement. Funnels and event-property breakdowns rate `high` on almost every project, whatever the window, so ask once for the whole analysis rather than per query. `very_high`: never run it; narrow it.
- **Aggregate only.** Never call `list_customers`, `list_customers_in_segment`, `get_customer_properties` or `list_customer_events`. Never break down by free-text, URL, email or ID properties.
- **Large responses.** `get_event_schema` can exceed 200,000 characters on large projects. If the client saves it to a file, extract event names and the few property names and types you need.
- **Prefer a test project for trying queries**, but measure the funnel in the project the user cares about (usually production): a sandbox often has no purchases.
- Read [references/eql-patterns.md](references/eql-patterns.md) before writing any EQL. It has the tested funnel and value queries and the syntax traps.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/funnel_leaks.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the project

Call `list_cloud_organizations`, then `list_projects`. If there's more than one organisation or project, list them by name and **ask which to use. Never guess.** Say whether it's a sandbox or production project.

### 2. Map the funnel to real events

1. Call `get_event_schema`. Find the project's names for each step. Common names, which you must confirm:

   | Step | Usual event | Also seen |
   |---|---|---|
   | Product view | `view_item` | `product_view`, `view_product` |
   | Add to cart | `cart_update` with `action` = `add` | `add_to_cart`, `cart_add` |
   | Checkout | `checkout` | `checkout_start`, `begin_checkout`, `cart_update` with a checkout `action`. **Many projects have none**: then skip the step and say so |
   | Purchase | `purchase` | `order`, `purchase_item` (one event per line item: don't use it for customer counts or order value) |

2. For each step event, note the properties you need and their **types**:
   - an `action` property on `cart_update` (check its values with the value-breakdown query in the reference: in testing, `add` and `remove`);
   - an order value on `purchase` (`total_price`, numeric);
   - a cart value on `cart_update` (`total_price` is usually the **running cart total**, so average it; don't sum it);
   - breakdown properties that exist on the **first step's** event: `device`, `os`, `browser`, `location`; and on `session_start`: `utm_source`, `utm_medium`, `source`, `referrer`.
3. If a property you want doesn't exist, skip that breakdown and say so. Never invent a name: the cost estimator doesn't check names, so a typo only shows up as a zero.

### 3. Look at existing funnels

Call `search_funnels`. If a saved funnel covers these steps, fetch it with `funnel_id` and read `funnel_steps.steps` (event and filters) and `funnel_steps.duration_filter` (the conversion window). Reuse its event filters, and tell the user their saved funnel exists so they can watch the fix there. Saved funnels can be incomplete (in testing, one had a single step): don't trust a funnel just because of its name.

### 4. Count the funnel

1. Run the overall funnel (pattern F1 in the reference), for example:

   ```
   funnel view_item followed by cart_update where .action = "add" followed by purchase in last 30 days within 7 days end
   ```

   It returns `data.total.counts`: the number of **customers** who reached each step in order, and `data.total.times`: the average seconds between steps (`-1` for the first step, or where no one converted).
2. **Check the purchase step against reality** (pattern F3). Count purchasers in the same window with a one-step funnel: `funnel purchase in last 30 days end`. If the funnel's last step is **under about half** of all purchasers, the purchase step is **not reliable**: purchases are probably tracked under a different customer identity (server-side or imported orders not merged with web visitors), or arrive late. In testing on a production project, only a few percent of purchasers appeared after a cart add. Then:
   - report the **view → cart** leak normally;
   - report **cart → purchase** as "can't be measured reliably", not as a leak;
   - hand off to `engagement-tracking-health` (identity and purchase tracking) and say what to check: the identifier on purchase events, and whether orders are imported.
3. **Breakdowns.** Funnels **don't accept `by`**. To compare devices or sources, filter the first step and run one funnel per value (pattern F2):
   1. find the top values with a value-breakdown query on the first step's event (pattern V1), for example `device` on `view_item`;
   2. run the funnel once per value, up to 4 values, one at a time.

   Note what the values mean: in testing, `device` held device families (`iPhone`, `Android`, `Other`), with desktop traffic under `Other`. `os` or `browser` may split better. For traffic source, start the funnel at `session_start` with a `utm_source` or `source` filter (pattern F4).
4. Optional, by step timing: a long average time from cart to purchase (`times`) suggests hesitation (shipping cost, payment options). Mention it, don't over-read it.

### 5. Size abandoned carts and order value

1. **Abandoned carts:** customers at the cart step minus customers at the next step, from step 4 (if the purchase step is reliable, or the next step is checkout). The script takes the first step named "cart" or "basket"; set `cart_step` (its index) in the JSON if yours is named differently.
2. **Average cart value** (pattern V2): `select avg event cart_update.total_price where .action = "add" by event cart_update.action grouping top 3 with null in last 30 days`. Read the `add` row.
3. **Average order value** (pattern V3): `select avg event purchase.total_price by event purchase.<low-cardinality property> grouping top 5 with null in last 30 days`. Weight the rows by their counts if there's more than one.
4. If a value property is empty (all rows 0 or null), try the other value fields, and say which you used. In testing, `price` on `cart_update` was empty while `total_price` was filled.

### 6. Put a revenue figure on each leak

If you can run Python, save the counts as JSON (format in the script's docstring) and run:

```
python3 <this skill's folder>/scripts/funnel_leaks.py funnel.json
```

Otherwise use the formulas in [references/revenue-at-stake.md](references/revenue-at-stake.md). In short:

- **Lost at a step** = customers at the step − customers at the next step.
- **Value walking away** = lost × (share of next-step customers who go on to buy) × average order value. Use average cart value instead for the last step if it's lower. This is an **upper bound**: it assumes every lost customer could have been recovered.
- **Realistically recoverable** = value walking away × recovery rate (the user's figure, or the default assumption).
- **Segment gap** = a segment's first-step customers × (overall conversion − the segment's conversion) × average order value, where positive. This shows which device or source under-converts most.
- Scale to a month or year only if the user asks, and say it's a straight-line projection.

Rank leaks by realistically recoverable value. Ignore steps or segments with fewer than about 100 customers: percentages swing too much.

### 7. Check the recovery flows

Use the method of the `engagement-scenario-explainer` skill. See [references/recovery-flows.md](references/recovery-flows.md) for what each flow should look like.

1. `search_scenarios` with `trigger_types=["onevent"]` (all statuses). These are the only scenarios that can react to a cart, view or purchase in time. Then repeat with `status="active"`. Also list `trigger_types=["repeated"]`: some teams run abandonment as a daily batch on a segment.
2. For each candidate (match names such as "abandon", "cart", "basket", "browse", "viewed", "post-purchase", "thank", "review", "cross-sell"; but **confirm from the trigger, not the name**), call `search_scenario_nodes` (via `call_tool`) with no `node_id` for the graph map, then fetch the `on-event-trigger` node to read **which event** it listens to, and any property filter.
3. Classify each flow type as:
   - **Active:** an active scenario triggers on the right event and has a message node (email, SMS, push) on a connected path.
   - **Weak:** exists but inactive, draft or paused; or the first message waits more than about 24 hours (cart) or 48 hours (browse); or it sends on one channel only when the project uses several; or no exit condition when the customer buys (check for a condition on `purchase` before each send).
   - **Missing:** no scenario triggers on that event.
4. Optional, and only if `estimate_eql_cost` says `low` or `medium`: count recent sends from a flow with the `campaign` event (pattern R1) to confirm it's actually running.

Rank missing or weak flows by the leak they would address, from step 6.

## Output

```
## Funnel leaks: <project>, <window> (conversion window <n> days)

**Verdict:** <one sentence: the biggest leak, its value, and the fix>

| Step | Customers | Step conversion | Lost | Value walking away | Recoverable (at <rate>) |
|---|---|---|---|---|---|
| Viewed a product | ... | — | | | |
| Added to cart | ... | ...% | ... | $... | $... |
| Purchased | ... | ...% | ... | $... | $... |

**Biggest gaps by <device / source>:** <segment: conversion vs overall, gap $...>
**Abandoned carts:** <n> customers, average cart $..., about $... left in carts
**Data caveats:** <purchase step reliability, missing checkout event, empty value fields>

### Recovery flows
| Flow | Status | Evidence | Leak it addresses |
|---|---|---|---|
| Cart abandonment | Active / Weak / Missing | ... | $... |
| Browse abandonment | ... |
| Post-purchase | ... |

### Next steps
1. <fix>: <why, value>. Hand-off: <engagement-segment-builder / engagement-scenario-explainer / engagement-tracking-health>
```

Round figures (for example "about $42,000") and label upper bounds and assumed rates as such. Keep it under about 40 lines.

## Safety

This skill is **read-only**. It never creates, changes, starts or stops scenarios, segments, funnels or anything else.

- It reads aggregate counts only, never individual customers or their events.
- It never quotes email, SMS or webhook content from scenario nodes; they can contain personal data.
- If the user wants to build a recovery flow, hand off to `engagement-segment-builder` for the audience (it confirms before writing) and describe the scenario for them to build in the Engagement UI.
