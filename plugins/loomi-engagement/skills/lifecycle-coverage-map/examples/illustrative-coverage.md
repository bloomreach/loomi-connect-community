# Example: lifecycle coverage (illustrative)

**This example is illustrative.** The method and the kinds of finding come from read-only runs against a demo Engagement project (where every lifecycle scenario was a draft and two templates had unconnected triggers), but the project name, scenario names and every number have been invented.

**Prompt:** "Which lifecycle flows are we missing, and which should we build first?"

## Lifecycle coverage: example-retail-prod, 3 November 2026

**Verdict:** 2 of 8 flows are live. The biggest gap is cart abandonment: the flow is live but sends its first email after two days, about $1,600 a month at stake. Fix it with `scenario-qa`, then build win-back.

| Flow | Status | Scenario (evidence) | Problems | Monthly audience | At stake / month | Next |
|---|---|---|---|---|---|---|
| Welcome | Live | Welcome series (on-event trigger on `consent`, accept) | — | — | — | engagement-scenario-performance |
| Browse abandonment | Draft | Viewed but left (on-event `view_item`, SMS only) | — | ~3,000 | ~$960 | scenario-qa |
| Cart abandonment | Weak | Basket reminder (on-event `cart_update`) | first email after 48 hours (over 24) | ~2,000 | ~$1,600 | scenario-qa |
| Post-purchase | Weak | Thank you (on-event `purchase`) | trigger isn't connected; no message on a connected path | not sized | — | scenario-qa |
| Replenishment | Live | Order follow-up (on-event `purchase`, first email after 30 days) | — | — | — | engagement-scenario-performance |
| Birthday | Stopped | Monthly treat (daily trigger; "Birthday is today" condition) | — | ~1,000 | ~$960 | scenario-qa |
| Win-back | Missing | — | — | ~2,000 | ~$1,300 | engagement-scenario-builder |
| Sunset | Missing | — | — | ~10 | too few to value | engagement-scenario-builder |

**Assumptions:** AOV $80 (30-day AOV query); reachable share 40% (default assumption: run `contactability-audit` for the real figure); conversion rates per flow from `rules.json` (planning assumptions, not benchmarks). Up to about $4,800 a month in all; one customer can be in several flows.
**Unconfirmed:** "Welcome back banner" (name only; triggers on `session_start`, so it's a web-layer helper). "Sunset unengaged subscribers" (draft, not checked).
**Not possible yet:** none.

### Next steps
1. Cart abandonment: shorten the first wait to 1–4 hours and add a purchase check before each send. Hand-off: `scenario-qa`.
2. Win-back: build a daily flow for buyers crossing 90 days without an order, with a holdout. Hand-off: `engagement-scenario-builder` (and `winback-opportunity` for value tiers).
3. Post-purchase: connect the trigger in "Thank you", then check it. Hand-off: `scenario-qa`.
