# Journey health checks

Each check names its evidence, its severity and the usual fix. The fix is always for the user to make in Engagement; this skill never edits a flow.

Severity:

- **Action:** customers who should get a message aren't getting it now, or are getting something broken.
- **Review:** probably wrong, but a person should confirm.
- **Info:** worth knowing; no change needed.

The script reports `high` for Action and `medium` for Review. The numeric thresholds live in `references/rules.json`, which the script reads. Use the same keys when you work by hand.

## Counting a step by hand

Drop rows that are all zeros. Status groups are in `rules.json`. Per step:

- enqueued = the largest of the `enqueued_statuses` (`enqueued` for email, `sent` for SMS and push);
- bounces = the sum of the `bounce_statuses` (`hard_bounced`, `soft_bounced`, and the older `hard_bounce`, `soft_bounce`, `failed`);
- reached = max(enqueued, `delivered` + bounces) + `suppressed` + `aborted` + `enqueue_failed`;
- not delivered = reached − `delivered`, **except** when the step has enqueued messages but no `delivered` and no bounces at all (SMS and push record only `sent`): then delivery is unknown, and not delivered = `suppressed` + `aborted` + `enqueue_failed`;
- lost share = not delivered ÷ reached; errors = `enqueue_failed` + bounces.

A cell that isn't a number ("NA") is missing, not 0.

## From the numbers

| Check | Evidence | Severity | Usual fix |
|---|---|---|---|
| Active, but sends nothing | Active flow with at least one message step and no `campaign` events for those steps in the period (and created before the period, or at least one trigger cycle ago) | Action | Find the first condition that lets nobody through (query 5 in `references/queries.md`) and fix it; or, for an event trigger, check the event still arrives |
| Step mostly not delivered | Lost share (reached minus delivered, over reached) at or above `lost_share_high`, with at least `min_reached` reached | Action | Depends on the reason (below) |
| Step partly not delivered | Lost share at or above `lost_share_medium` | Review | Depends on the reason |
| Errors | Not queued plus bounces at or above `error_share_medium` of reached | Review | Depends on the reason |
| Deliveries dropped | Delivered in this period at or below `drop_ratio` of the previous period (previous at least `drop_min_previous`) | Action if it fell to 0, otherwise Review | Read the day-by-day trend (query 4); look for a condition that lets customers through only once, an audience that ran dry, or a trigger event that stopped |
| Not-delivered share rose | Lost share up by `lost_share_rise_points` or more | Review | Read the reasons for both periods |

### Reading the reason (query 3)

| Status and `message` | What it usually means | Fix |
|---|---|---|
| `suppressed`, "has not given consent for this category" | The step's consent category isn't one the audience has | Use the consent category the audience opted into, or filter the audience on that consent before the step |
| `suppressed`, frequency policy wording | The frequency policy holds the message back | Review the policy, or accept it as intended |
| `aborted`, the text of a template `abort` (for example "No qualifying products available") | The template stops when it has nothing to show, usually recommendations or cart items | Add a fallback (another engine, popular items) or a condition before the step that checks there's something to show |
| `enqueue_failed`, "Rendering failure … Timeout" | The template timed out, usually a recommendation call | Ask for fewer items, use a lighter engine, or add a fallback |
| `enqueue_failed` with no message | Unknown failure before sending | Raise it with Bloomreach support, with the step and dates |
| `hard_bounced`, `soft_bounced`, `failed` (not read by query 3) | The provider refused the message | Use `deliverability-trend` for the error codes and mailbox providers. Don't break bounces down by `message`: bounce texts often quote the recipient's address |

## From the flow's configuration

Read every condition and wait on the path to each message step (`customer_filter.filters`, `formula`, the node `name`).

| Check | What to look for | Severity |
|---|---|---|
| Hard-coded leftover | A constant that ties the whole flow to one product, brand, size or SKU (a `title` or `product_id` "contains" or "equals" a value) when the node's name doesn't say so | Action if the flow also under-sends, otherwise Review |
| Narrow audience by design | The same, but the node name states the value (for example "Bought brand X, size M") | Info: confirm the audience is still big enough, and size it |
| Test value | A single email address, customer ID or phone number in a condition, a sender name or step name that reads like a placeholder ("test", "placeholder", "unnamed", random letters), or a flow name with "test" or "copy" that is active and sending | Review. Never repeat the address or ID |
| Date in the past | An absolute `date_filter` (`absolute: true`) whose `to_date` is before today, or a scenario-level `to_date` in the past | Action: the condition can't match any more |
| Once-ever frequency cap | A condition named like "received at most N times" that is built as a `funnel_steps` "has received" check on the `campaign` event, with no count, and the flow continues on the "doesn't match" output | Action when deliveries dropped: each customer gets the flow only once in the condition's window. Build it as a count (`embedded_aggregate` count ≤ N) instead |
| Condition nobody passes | A condition on a customer property no customer has (or that isn't in `get_customer_property_schema` at all: Engagement saves it anyway), or an event that hasn't been tracked in the window | Action if it's required on the path; Info if it's negated (`!D`), where it lets everyone through |
| Wait that leaves nobody | A message step after a wait gets 0 while the step before it delivered at least `min_reached`, and the period is longer than the wait | Review: check the conditions after the wait, and the wait's own settings |

## What not to flag

- Steps that send nothing by design: splits, set-property and add-event steps, limits and waits.
- Flows whose only trigger is a manual "run now".
- Flows created during the period: judge them only from their creation date.
- Small steps (under `min_reached`): list them, don't judge them.
- Pre-launch content problems (links, Jinja, compliance): those belong to `scenario-qa`.
