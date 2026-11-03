# Example: contactability audit (illustrative)

**This example is illustrative.** The method, the query shapes and the kinds of finding come from read-only runs against a demo Engagement project, but the project name, category names and every number have been invented.

**Prompt:** "How many of our customers can we actually reach, and is it getting better?"

## Contactability: example-retail-prod, base = bought in the last 365 days (about 10,000 customers), 3 November 2026

**Verdict:** Only 25% of last year's buyers can be emailed, although 80% gave an email address, and opt-outs have beaten opt-ins for two months running. Start with a re-permission campaign for the 55% with an address but no consent.

| Channel | Has identifier | Reachable (with consent) | Consent gap |
|---|---|---|---|
| Email | 80% (~8,000) | 25% (~2,500) | 55% |
| SMS | 40% (~4,000) | 35% (~3,500) | 5% |
| Push | 15% (~1,500) | not measured | — |
| Any channel | | 40% (~4,000) | |

**High-value customers:** 35% of about 1,000 (lifetime spend over $240) can't be reached on any channel.

**Consent by month** (all categories): May +120 / −40 = +80; Jun +65; Jul +130 / −300 = −170; Aug +50; Sep −30; Oct −30. Shrinking for the last two months; July's opt-outs were 6× a usual month.

**Consent categories:** Newsletter and SMS in use. "Partner offers" is defined but nobody holds it. "Surveys" had no consent events in 180 days. Consent events also use "promo_legacy", which isn't defined. Push can send without a category (general consent).

### Findings
1. [High] 35% of high-value customers can't be reached → ask for consent at checkout and in the account area; reach them on site with a web layer meanwhile.
2. [High] Opt-outs beat opt-ins in each of the last 2 months → check send frequency and what went out in September and October (`engagement-campaign-digest`).
3. [High] Email reaches only 25% of buyers → re-permission audience for the 55% with an address but no consent (`segment-opportunity-finder` pattern P8, then `engagement-segment-builder`).
4. [Medium] July opt-out spike (300) → find the July send or form change behind it.
5. [Medium] "Partner offers" category unused → remove or document it with whoever owns privacy.

**How this was measured:** email = `newsletter` category (used by the live welcome scenario's email steps); SMS = `sms`; base = purchase in the last 365 days; 12 aggregate queries (customer counts `medium`, consent breakdowns `high`); push reachability skipped: no push token property in the customer schema.
