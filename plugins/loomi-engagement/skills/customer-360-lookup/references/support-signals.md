# Support signals: event types and what to flag

Event type and property names vary by project. These are the **common** Bloomreach Engagement conventions. Use the names you actually see in the customer's events; if you can't find an event type, say so rather than guessing a name. `list_customer_events` returns each event with a `type`, a Unix `timestamp` and a `properties` object.

## Orders

| Event type (typical) | Properties to read | Flag when |
|---|---|---|
| `purchase` | `purchase_id` or `order_id`, `purchase_status` or `status`, `total_price`, `currency`, `payment_type` | status is failed, cancelled, declined, refunded, returned or pending for more than a day |
| `purchase_item` | `purchase_id`, `product_id`, `title`, `quantity` | (use only for "what did they buy") |
| `refund`, `return`, `order_status` | order ID, reason, status | any in the window |
| `checkout`, `cart_update` | `action`, `total_price` | several checkouts with no matching purchase on the same day |

The same order can appear several times as its status changes (for example `pending` → `success`). Group by order ID and report the latest status.

Never show `payment_type` details beyond the method name ("card", "PayPal").

## Messages (`campaign` event)

Bloomreach records message activity as `campaign` events. Useful properties: `action_type` (email, sms, push, webhook…), `campaign_name` or `action_name`, `status`, and sometimes `message` or `error`.

| `status` (typical) | Meaning | Flag when |
|---|---|---|
| `enqueued`, `delivered` | sent and accepted | — |
| `opened`, `clicked` | engagement | — (useful context) |
| `hard_bounced` (or `hard_bounce`) | the address doesn't exist | always |
| `soft_bounced` (or `soft_bounce`) | temporary failure | 3 or more in a row |
| `complained`, `spam` | marked as spam | always |
| `unsubscribed` | unsubscribed via the message | always |
| `failed`, `dropped`, `suppressed` | not sent (often consent, frequency cap or invalid address) | always, with the reason if given |

"Why didn't they get the email?" is usually answered by a `failed`/`suppressed` status with a reason, consent, a hard bounce, or no matching `campaign` event at all (the customer wasn't in the audience).

## Consent (`consent` event)

Typical properties: `category` (for example `newsletter`, `other`), `action` (`accept` or `reject`), `valid_until`, `source`, `timestamp`.

- The **latest** `consent` event per category is the current state.
- Flag a `reject`, and an `accept` whose `valid_until` has passed.
- To explain what a category covers and which channels need consent, call `get_consent_settings` via `call_tool`. It returns the project's categories and `general_consent` (which channels are sent without a consent category).

Also check opt-in properties on the profile, such as `email_opt_in` or `sms_opt_in`. If they disagree with the consent events, flag it: campaigns may use either.

## Activity

| Event type (typical) | Use |
|---|---|
| `session_start`, `session_end`, `page_visit`, `view_item`, `view_category` | collapse into one line per day ("5 visits, 12 product views") |
| `identify`, `customer_merge` (if present) | flag recent merges: they explain sudden changes in history |
| `banner`, `survey` | show only if relevant to the question |
| `error`, `app_crash` or similar | flag repeated errors |

**Sudden stop:** if the customer was active most weeks and then nothing for 30+ days, say so. It may be churn, or a tracking or identity problem (for example a new device without login).

## Identity

- Only a `soft` identifier (cookie) and no `hard` one: an anonymous visitor. Campaign channels usually won't reach them.
- Several `hard` identifiers of the same type, or IDs that look like test values: flag as a possible duplicate or test profile.
