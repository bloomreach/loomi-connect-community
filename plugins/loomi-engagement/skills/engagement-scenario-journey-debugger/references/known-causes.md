# Known causes, by node type

Each item is marked **[doc]** when Bloomreach documentation states it, or **[inference]** when it follows from how the platform works but isn't stated outright. Never present an [inference] item as confirmed in a verdict. Sources are listed at the end.

## Contents

1. Scenario status
2. Triggers
3. Conditions and time filters
4. Waits
5. Limits and A/B splits
6. Identity and merges
7. Action outcomes and `campaign` statuses
8. What Loomi Connect can't see

## 1. Scenario status

- **[doc]** Stopping a scenario drops every customer held in a wait node, and so can a technical error. (Troubleshoot scenarios)
- **[doc]** Now and On date triggers go inactive after they've run once and need a manual reset to run again. A scenario can be "active" with a spent trigger. (Scenario triggers)
- **[doc]** If a scenario has more than one trigger, they process in sequence: the second waits until the first has completely finished. A customer can look "late" for this reason. (Scenario triggers)

## 2. Triggers

**Events that never start a scenario [doc] (Scenario triggers):**

- `campaign` events with status `enqueued`, `enqueue_failed`, `sent`, `failed` or `suppressed`, and any `campaign` event with no status at all (A/B test events, for example).
- `merge` events.
- `consent` events created by a manual change in the UI (their `source` is `CRM`).
- Events created by an Add event node, unless that node has scenario triggering allowed.
- Ad audience node operations (add, remove, remove from all custom audiences).

**On event trigger limits [doc] (Scenario triggers):**

- No Jinja in the trigger.
- No derived attributes (running aggregates, expressions, event segmentations) in the trigger filter. These belong in a condition node straight after the trigger.
- A filter of "attribute is false" also matches events where the attribute doesn't exist at all, unless the filter also has "attribute has value". The reverse trap matters too: if the author expected missing values to be excluded, they weren't.

**Imports:** **[doc]** bulk-imported events can start On event scenarios when the import allows it, and large imports can overwhelm processing. (Troubleshoot scenarios) **[inference]** An event visible on the profile that arrived by import may never have reached the scenario.

**Filter mismatches [inference]:** trigger filters compare exactly. Common misses are case differences, a number tracked as a string, a renamed attribute, and a value with trailing whitespace. Compare the event's actual property value with the filter's operand character by character.

**API triggers [inference]:** Loomi Connect has no record of inbound API trigger calls. Whether a call was made for this customer can only be confirmed from the calling system's logs.

## 3. Conditions and time filters

- **[doc]** In scenario filters, relative time filters ("in the last 7 days") use UTC, while absolute time filters use the time zone set in the author's user settings. A customer near a day boundary can fall either side depending on which kind the filter uses. (Scenario actions and operators)
- **[doc]** Conditions can use Jinja (for example trigger event properties) when personalisation is enabled on the node. A Jinja condition that errors or renders empty is a candidate cause. (Scenario actions and operators)
- **[inference]** A condition is evaluated at the moment the customer arrives at it. Current profile data can differ from what was there then, so always compare property last-updated timestamps and event timestamps with the time the customer reached the node.
- **[inference]** Segmentation forks and conditions that reference a segmentation use that segmentation's current definition. If the definition was edited after the run, today's evaluation can disagree with what happened.

## 4. Waits

- **[doc]** Waits longer than 7 days carry a higher risk of customers being dropped (by a stop or a technical error). (Troubleshoot scenarios)
- **[doc]** Changing a wait doesn't affect customers already waiting; they keep the wait time they started with. (Scenario actions and operators)
- **[doc]** A one-month wait runs to the same date next month, so it can be 28 to 31 days. (Scenario actions and operators)
- **[doc]** Silent hours pause delivery during configured hours or days, at project level or overridden in a wait node. (Scenario actions and operators)
- **[inference]** Before calling anything a failure, check whether trigger time plus the wait is still in the future. The customer may simply still be waiting.

## 5. Limits and A/B splits

- **[doc]** A customer limit node sends customers to its success output in arrival order until the limit is reached; everyone after that goes to the unsuccessful output until the counter resets. It starts failing above 1,000 distinct drill-down groups. (Scenario actions and operators)
- **[doc]** A/B split assignments are recorded as `campaign` events with `action_type` of `split`, carrying `variant`, `variant_id` (which starts at 0) and `new_choice`. (System events)
- **[doc]** A/B tests with automatic winner distribution only work with Now and Scheduled triggers; manual distributions also work with On event. (Scenario actions and operators)

## 6. Identity and merges

- **[doc]** `merge` events record `source_internal_ids`, `destination_internal_id`, and the external IDs before and after in `original_external_ids` and `final_external_ids`. (System events)
- **[inference]** A scenario evaluates the profile as it exists when the trigger fires. If the trigger event was tracked on an anonymous profile that merged with the identified one later, the scenario saw a profile without the contact details, consent or properties the identified profile now has. Compare the merge timestamp with the trigger timestamp.
- **[inference]** A profile URL copied before a merge can point at an ID that no longer exists. Ask for a fresh link.

## 7. Action outcomes and `campaign` statuses

**Missing contact details [doc]:** the email action needs the `email` attribute to have a value, and the SMS action needs `phone`. A missing contact property does not produce an `enqueue_failed` event. (Scenario actions and operators; System events) **[inference]** Whether any other event is recorded isn't documented; in practice the send is usually skipped with nothing on the profile, so the customer can pass every node and still leave no trace.

**Status meanings [doc] (System events), paraphrased:**

| Status | What it tells you |
|---|---|
| `enqueued` | Handed to the sending provider. Engagement did its part. |
| `enqueue_failed` | Engagement couldn't hand the message over. |
| `suppressed` | Blocked by frequency policy, consent policy or a suppression list. Documented for email. |
| `failed` | Provider communication error, **or** the node itself failed while running, for example a Jinja error. Tracked even when nothing was sent. |
| `aborted` | The template called the Jinja abort function with a custom message. |
| `delivered`, `opened`, `clicked` | It worked. The problem is downstream (inbox placement, the customer, the client's own expectations). |
| `soft_bounced`, `hard_bounced`, `preblocked`, `complained` | Provider-side delivery failures. |
| `rejected` | Provider rejection for SMS, MMS, WhatsApp and RCS. |
| `sent` | SMS and push: handed over. These channels record no `delivered`, so `sent` is as far as the trail goes. |

Older data may use the previous names `dropped` and `soft bounced` (now `soft_bounced`), `bounced` (now `hard_bounced`) and `rejected` (now `preblocked`, for email). Check for both. (System events) Some projects also spell them `hard_bounce`, `soft_bounce` and `unsubscribe`.

**Contact details that arrive late [inference]:** a profile can be created by one source (for example a consent event from a third-party sign-up pop-up) while the `email` or `phone` property is written later by a separate sync. If the scenario reaches the action before the sync runs, the send is skipped and nothing is recorded, yet the profile looks complete when you check it afterwards. Compare the property's last-updated timestamp with the time the customer reached the action. Bear in mind that last-updated shows the most recent write: if the sync rewrites the value regularly, the timestamp can be later than the first write. So treat a gap as "likely" unless the timing pattern is clear, for example several test profiles whose email values all arrive just after the hour.

**Frequency policy [doc]:** if an email action uses manually chosen recipients, it ignores frequency policies. (Scenario actions and operators)

**Consent [inference]:** the `campaign` event records the action's `consent_category`. Compare it with the customer's `consent` events for that category (action and validity dates) at the time of sending.

**Mobile push [doc]:** SDKs released on or after 26 Sep 2025 store push tokens as `notification_state` events, which expire after 90 days; the `default-application` app ID also falls back to the legacy profile attributes. A customer who hasn't opened the app in 90 days may have no usable token. (System events)

## 8. What Loomi Connect can't see

Say these plainly in the "Couldn't check" section when they matter:

- A per-customer trace of which nodes were passed. Only actions and splits leave events. The scenario's Evaluation tab in the UI shows aggregate counts per node, not individuals.
- Inbound API trigger calls.
- Customer limit node counters.
- Historical property values. Only the current value and its last-updated time are available.
- Masked PII values. `******` means "has a value", not "empty".
- Data that never arrived. If the trigger event or a property is missing from the profile entirely, Loomi Connect can't tell you why. The sending system's own logs are the place to look (failed deliveries, a wrong endpoint, HTTP instead of HTTPS, a malformed URL).
- `list_customer_events` returns at most 500 events per page and can skip at most 999, so very busy profiles need a tight `days_back` window and an `event_types` filter.

## Sources

- System events: https://documentation.bloomreach.com/engagement/docs/system-events
- Scenario triggers: https://documentation.bloomreach.com/engagement/docs/scenario-triggers
- Scenario actions and operators: https://documentation.bloomreach.com/engagement/docs/scenario-actions-and-operators
- Troubleshoot scenarios: https://documentation.bloomreach.com/engagement/docs/troubleshoot-scenarios
- Loomi Connect guides: `scenario-exploration`, `customer-lookup`, `navigation` (via `get_guide`)

The [doc] items were checked against these pages on 13 Nov 2026.
