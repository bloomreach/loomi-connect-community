# loomi-playbooks

Playbooks chain existing Loomi Connect skills into one job, from finding a problem to fixing, testing and measuring it. Each skill on its own stops at "hand this to skill X"; a playbook carries the result across for you, and picks up again in a later session when a test or a flow has had time to run.

## Operating rhythms

Start here: these run the others.

| Skill | What it does | Access |
|---|---|---|
| [playbook-weekly-triage](skills/playbook-weekly-triage/) | Monday triage: which runs are due or can be skipped this week, the weekly briefing, why revenue moved, and the playbook to start or resume for each top problem | Read-only |
| [playbook-quarter-close](skills/playbook-quarter-close/) | Close a quarter: measure the changes playbook runs shipped that nobody confirmed, build a QBR with what the work earned, plan next quarter, and name the playbooks to run next | Read-only |
| [playbook-new-project](skills/playbook-new-project/) | First 30 days of a new project: orientation, go-live checklist, tracking, feed, catalog and lifecycle checks, then a 30-day plan naming the playbooks to run in order | Read-only |

## Search (Discovery)

| Skill | What it does | Access |
|---|---|---|
| [playbook-test-and-learn](skills/playbook-test-and-learn/) | Find the Discovery rule costing a query money, A/B test a fix, roll out the winner and confirm it holds, across sessions | **Writes** |
| [playbook-search-vs-category](skills/playbook-search-vs-category/) | Redirect a category-name search that lands worse than its category page to that page, and check it helped, across sessions | **Writes** |
| [playbook-findability](skills/playbook-findability/) | Fix dead-end searches at the root: product data suggestions, searchable attributes and synonyms, then count the searches that recovered | **Writes** |
| [playbook-supplier-review](skills/playbook-supplier-review/) | Score a brand, A/B test a boost on a query it's buried on, keep the winner and take the result into the supplier meeting, across sessions | **Writes** |
| [playbook-product-opportunity](skills/playbook-product-opportunity/) | Pick a product worth acting on, fix its listing or A/B test a boost or bury, roll out the winner and confirm it holds | **Writes** |

## Search and Marketing

| Skill | What it does | Access |
|---|---|---|
| [playbook-search-demand-to-revenue](skills/playbook-search-demand-to-revenue/) | Turn one site search into a search fix and a campaign: find it, triage it, add a synonym or landing collection, draft an email or SMS, read the send and measure the result | **Writes** |
| [playbook-catalog-truth](skills/playbook-catalog-truth/) | Make search, recommendations and email agree on product data: parity, price and variant checks, Engagement catalog fixes, a list for the feed team, and a recheck | **Writes** |
| [playbook-peak-event](skills/playbook-peak-event/) | Plan, check and review one peak event: campaigns, landing collections, readiness, vouchers, send preflight and collisions, then what moved revenue | Read-only |
| [playbook-revenue-drop](skills/playbook-revenue-drop/) | Incident runbook for a revenue drop: explain it, check only what's left (feeds, search API, flows, a recent change), roll back a harmful rule and confirm recovery | **Writes** |
| [playbook-monthly-hygiene](skills/playbook-monthly-hygiene/) | One monthly sweep of Discovery rules and redirects and Engagement assets, with one plan to approve per write stage and a safe deletion order for Engagement | **Writes** |

## Marketing (Engagement)

| Skill | What it does | Access |
|---|---|---|
| [playbook-lifecycle-gap](skills/playbook-lifecycle-gap/) | Find a missing or weak lifecycle flow, clone a proven one as a draft, fix and QA it, then once you switch it on check it's sending and measure its revenue | **Writes** |
| [playbook-brief-to-results](skills/playbook-brief-to-results/) | Turn a brief into an email or SMS draft, QA it, preflight the week and check clashes once it's scheduled, then read the results into the next brief | **Writes** |
| [playbook-deliverability-recovery](skills/playbook-deliverability-recovery/) | Trend deliverability, find over-messaging and consent gaps, launch a sunset or re-permission flow as a draft, then recheck the trend | **Writes** |
| [playbook-prediction-activation](skills/playbook-prediction-activation/) | Find an unused prediction, build a segment on its scores, launch a flow for it as a draft, then measure it once it's live | **Writes** |
| [playbook-lapsed-customers](skills/playbook-lapsed-customers/) | Size lapsed customers, sharpen the audience, build the segment and a win-back flow as a draft, then measure who came back | **Writes** |

## How playbooks work

- **They don't repeat any skill's logic.** Each stage loads the skill that does it, so install the plugins those skills are in (each playbook's README lists them).
- **A hand-off file links the stages.** It holds the context, the stages, the findings and a change log, in the shape in [docs/hand-off-format.md](../../docs/hand-off-format.md). Keep the files (`*.handoff.json`) in one folder: the weekly triage and quarter close playbooks read them all.
- **Writes stay with the stage skills.** Every write is shown and confirmed in the skill that makes it. A yes to a playbook is never a yes to a write.
- **Customers with one product** can run the playbooks that span both: stages for the product they don't have are offered as skips.
- **Marketing playbooks measure before and after.** There's no skill yet that sets up an A/B test in Engagement, so they compare against a control with `change-impact-tracker` rather than testing.

To add a playbook, see [CONTRIBUTING.md](../../CONTRIBUTING.md).
