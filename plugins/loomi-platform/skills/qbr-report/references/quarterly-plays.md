# Quarterly plays

Turn the QBR's evidence into **three to five plays for next quarter**. A play is bigger than a weekly action: a programme of work with an owner, a measure and a skill that does or starts it. Choose by money at stake, then by how sure the evidence is, then by effort.

## Signals and plays

| Signal in the QBR | Play | Skill |
|---|---|---|
| A tracking or feed problem made part of the quarter unreliable | Fix the data first, and re-baseline the KPIs | `data-feed-health`, `engagement-tracking-health` |
| Revenue or conversion moved more than about 5% and the cause isn't clear | Find the drivers before planning around them | `revenue-anomaly-explainer` |
| High-revenue searches lost conversion or revenue over the quarter | Diagnose and fix the top searches | `discovery-query-diagnosis` |
| Dead-end searches add up to real money | Run a zero-results programme (synonyms, redirects, catalog gaps) | `discovery-zero-results-triage`, `discovery-synonym-review` |
| Rising search themes, or new queries with demand | Merchandise the demand, and turn it into campaigns | `discovery-trending-searches`, `search-demand-to-campaign` |
| Categories with low conversion or high bounce, or a shared pattern across several | Review the category pages, filters and grids | `discovery-category-health`, `facet-optimizer` |
| Products with views but few sales, or hidden gems | Boost, bury and fix product pages | `product-opportunity-finder` |
| A brand fell, or brands are over- or under-exposed | Prepare supplier conversations and ranking changes | `brand-performance-review` |
| Few or no experiments ran, or tests ended without a decision | Plan a testing roadmap: one test a month | `discovery-experiment-setup`, `discovery-experiment-readout` |
| Rules expired but still on, or lots of rule churn | Clean up merchandising rules before peak | `discovery-rule-audit` |
| Device gap (mobile RPV far below desktop) | Mobile-first fixes on the top pages and searches | `discovery-search-health`, `discovery-category-health` |
| Email click or delivery rates fell over the quarter | Review campaigns and deliverability | `engagement-campaign-digest` |
| Lifecycle flows weak or missing (cart, browse, post-purchase, win-back) | Build or fix the always-on flows | `funnel-leak-finder`, `winback-opportunity`, `engagement-scenario-performance` |
| Audiences nobody targets | Add segments and campaigns | `segment-opportunity-finder` |
| Recommendations look stale, or catalogs disagree | Audit engines and catalog parity | `recommendation-model-audit`, `catalog-parity-check` |
| A sale or peak falls in the next quarter | Plan it and check readiness | `campaign-planner`, `peak-readiness-check` |

## Estimating money at stake

Label every figure as an upper bound for a quarter:

- **A falling search, category, product or brand:** its revenue change against the previous quarter (from the movers).
- **A problem search or category:** `revenue_at_stake` from the issues list.
- **Dead ends:** the dead-end line's `revenue_at_stake` (sessions × typical revenue per visit).
- **A device gap:** mobile visits × (desktop RPV − mobile RPV) × a share you can realistically close (say 10–20%; state it).
- **A data problem:** don't put a figure on it. Put it first.

## Writing the play

One line each: **what**, with the specific searches, categories or flows; the **evidence** in a few words; the **measure** for next quarter's QBR; and the **skill**.

> 1. **Fix the top 10 converting searches that slipped**: "boots" and "rain jacket" lost $41k against Q2 as conversion fell 1.2 points. Measure: search RPV back to Q2's $16.07. → `discovery-query-diagnosis`

Avoid generic advice ("improve search"). If fewer than three plays have real evidence, list fewer and say so.
