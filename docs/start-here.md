# Start here

This guide is for merchandisers, ecommerce managers and CRM teams who run an online store on Bloomreach. It points you to the right skill for the job you're doing.

You don't need to remember skill names. Ask in your own words, for example *"how did search do last week?"*, and the assistant picks the right skill. The names below help you see what's possible, and let you call a skill directly when you want to.

Before you start, [connect Loomi Connect](connecting-loomi-connect.md) and install the plugins (see the [README](../README.md#install)).

## Every Monday

| Ask | Skill |
|---|---|
| "Give me the weekly briefing" | [weekly-ecommerce-briefing](../plugins/loomi-platform/skills/weekly-ecommerce-briefing/): KPIs, movers, marketing, health alerts and three things to do this week |
| "What are our top searches and categories, and which have problems?" | [weekly-ecommerce-briefing](../plugins/loomi-platform/skills/weekly-ecommerce-briefing/) for the weekly short list; [discovery-search-health](../plugins/loomi-discovery/skills/discovery-search-health/) and [discovery-category-health](../plugins/loomi-discovery/skills/discovery-category-health/) for the full picture |
| "What's trending in search?" | [discovery-trending-searches](../plugins/loomi-discovery/skills/discovery-trending-searches/) |
| "How did our emails and SMS do?" | [engagement-campaign-digest](../plugins/loomi-engagement/skills/engagement-campaign-digest/) |
| "Are our new products getting seen?" | [new-arrivals-tracker](../plugins/loomi-discovery/skills/new-arrivals-tracker/) |

## When something looks wrong

| Ask | Skill |
|---|---|
| "Why did revenue drop yesterday or last week?" | [revenue-anomaly-explainer](../plugins/loomi-platform/skills/revenue-anomaly-explainer/): a breakdown that adds up, with causes ranked by evidence |
| "Is our data and tracking OK?" | [data-feed-health](../plugins/loomi-platform/skills/data-feed-health/) (pixel, feeds, Data Hub) and [engagement-tracking-health](../plugins/loomi-engagement/skills/engagement-tracking-health/) (events and properties) |
| "Why is this search performing badly?" | [discovery-query-diagnosis](../plugins/loomi-discovery/skills/discovery-query-diagnosis/) |
| "Where are shoppers dropping out?" | [funnel-leak-finder](../plugins/loomi-engagement/skills/funnel-leak-finder/) |
| "A customer has a problem. What do we know about them?" | [customer-360-lookup](../plugins/loomi-engagement/skills/customer-360-lookup/): one customer's profile, recent activity and support flags, with personal data kept to a minimum |

## Improving search

Start with the health check, then go deeper where it points you.

1. [discovery-search-health](../plugins/loomi-discovery/skills/discovery-search-health/): overall search performance, and the queries worth investigating.
2. [discovery-zero-results-triage](../plugins/loomi-discovery/skills/discovery-zero-results-triage/): every search that leads nowhere, sorted into synonym fix, catalog gap, redirect or noise.
3. [discovery-query-diagnosis](../plugins/loomi-discovery/skills/discovery-query-diagnosis/): a deep dive into one query, with fixes ranked by impact.
4. [discovery-synonym-review](../plugins/loomi-discovery/skills/discovery-synonym-review/): synonyms that are bad, risky or missing a direction.
5. [autosuggest-audit](../plugins/loomi-discovery/skills/autosuggest-audit/): search suggestions that steer shoppers wrong, or leave out what sells.
6. [facet-optimizer](../plugins/loomi-discovery/skills/facet-optimizer/): filters that are missing, messy or unhelpful.
7. [discovery-redirect-audit](../plugins/loomi-discovery/skills/discovery-redirect-audit/): redirects that are broken, clash with each other, hijack broad searches, or are missing.

## Improving categories, products and brands

| Ask | Skill |
|---|---|
| "Which categories are underperforming?" | [discovery-category-health](../plugins/loomi-discovery/skills/discovery-category-health/) |
| "Which products should I boost, fix or clear?" | [product-opportunity-finder](../plugins/loomi-discovery/skills/product-opportunity-finder/) |
| "How are our brands doing? I have a supplier meeting." | [brand-performance-review](../plugins/loomi-discovery/skills/brand-performance-review/) |
| "What new collections should we create?" | [collection-suggester](../plugins/loomi-platform/skills/collection-suggester/) |
| "Build a pickleball collection" or "Which products belong with this search?" | [topic-collection-builder](../plugins/loomi-discovery/skills/topic-collection-builder/) |
| "Clean up our merchandising rules" | [discovery-rule-audit](../plugins/loomi-discovery/skills/discovery-rule-audit/) |
| "Are our dynamic categories working?" | [discovery-dynamic-category-review](../plugins/loomi-discovery/skills/discovery-dynamic-category-review/) |
| "Are our product recommendations set up well?" | [recommendation-model-audit](../plugins/loomi-engagement/skills/recommendation-model-audit/) |
| "Which products have weak data for Google and AI search?" | [product-data-audit](../plugins/loomi-product-data/skills/product-data-audit/) |
| "Improve the titles, descriptions and attributes for these products" | [product-data-enhancer](../plugins/loomi-product-data/skills/product-data-enhancer/): looks at the product images as well as the data, and suggests changes for you to review |

## Testing changes and checking they worked

1. [discovery-experiment-setup](../plugins/loomi-discovery/skills/discovery-experiment-setup/) (**writes**, after you confirm): set up an A/B test for a ranking change, with a preview first.
2. [discovery-experiment-readout](../plugins/loomi-discovery/skills/discovery-experiment-readout/): what the test showed. Ship it, keep running, or stop.
   For A/B tests in Engagement scenarios and campaigns, use [engagement-experiment-readout](../plugins/loomi-engagement/skills/engagement-experiment-readout/).
3. [change-impact-tracker](../plugins/loomi-platform/skills/change-impact-tracker/): "Did my change work?" Before vs after, adjusted for the site-wide trend, for changes made outside a test.

## Planning marketing

| Ask | Skill |
|---|---|
| "What campaigns should we run in the next 6–8 weeks?" | [campaign-planner](../plugins/loomi-platform/skills/campaign-planner/): retail calendar (default markets US, UK and EU), last year's results and current demand |
| "Which audiences should we be targeting?" | [segment-opportunity-finder](../plugins/loomi-engagement/skills/segment-opportunity-finder/) |
| "How much revenue are we losing from lapsed customers?" | [winback-opportunity](../plugins/loomi-engagement/skills/winback-opportunity/) |
| "Build me a segment of…" | [engagement-segment-builder](../plugins/loomi-engagement/skills/engagement-segment-builder/) (**writes**, after you confirm) |
| "Set up a flow that…" / "Change the wait in our welcome series" | [engagement-scenario-builder](../plugins/loomi-engagement/skills/engagement-scenario-builder/) (**writes** a draft, after you confirm) |
| "Move our Klaviyo emails into Bloomreach" | [convert-klaviyo-email-to-bloomreach](../plugins/loomi-engagement/skills/convert-klaviyo-email-to-bloomreach/) (**writes** drafts and uploads images, after you confirm) |
| "How is our abandoned cart flow doing?" | [engagement-scenario-performance](../plugins/loomi-engagement/skills/engagement-scenario-performance/) |
| "Write the Jinja for a recommendations block" / "Why won't this Jinja save?" | [engagement-jinja-writer](../plugins/loomi-engagement/skills/engagement-jinja-writer/): personalization, recommendations, cart items and social proof for weblayers, emails and scenarios |
| "Build me a newsletter pop-up" / "Why isn't our weblayer showing?" | [engagement-weblayer-builder](../plugins/loomi-engagement/skills/engagement-weblayer-builder/): pop-ups, banners and inline weblayers, with dynamic data from engagement-jinja-writer |
| "Is our welcome journey ready to go live?" | [scenario-qa](../plugins/loomi-engagement/skills/scenario-qa/): links, personalization and compliance in every send, with a go/no-go verdict |
| "Turn what people search for into a campaign" | [search-demand-to-campaign](../plugins/loomi-platform/skills/search-demand-to-campaign/) (**writes** a draft, after you confirm) |
| "Are we sending too much to the same people?" | [engagement-send-collision-check](../plugins/loomi-engagement/skills/engagement-send-collision-check/) |
| "Are we using our predictions?" | [prediction-activation-check](../plugins/loomi-engagement/skills/prediction-activation-check/) |

## Before a big event

Run [peak-readiness-check](../plugins/loomi-platform/skills/peak-readiness-check/) two to three weeks before Black Friday, a sale or a launch. It returns a go/no-go checklist covering data, rules, landing pages, event searches, sends, segments and on-site banners, with blockers first. Then work through what it finds:

- **Search fixes:** use the skills under *Improving search*.
- **Clashing sends:** use the send collision check.
- **Missing audiences:** use the segment builder.

Run it again a few days before the event.

## Housekeeping (monthly)

- [discovery-rule-audit](../plugins/loomi-discovery/skills/discovery-rule-audit/): expired, duplicate and unused rules.
- [engagement-scenario-explainer](../plugins/loomi-engagement/skills/engagement-scenario-explainer/) in audit mode: stale or broken automations.
- [onsite-experience-audit](../plugins/loomi-engagement/skills/onsite-experience-audit/): old banners, weblayers and surveys.
- [discovery-synonym-review](../plugins/loomi-discovery/skills/discovery-synonym-review/): leftover test synonyms.
- [engagement-asset-cleanup](../plugins/loomi-engagement/skills/engagement-asset-cleanup/): old drafts, test copies and unused segments, aggregates and reports.
- [project-access-review](../plugins/loomi-engagement/skills/project-access-review/) (quarterly): who has access to each project, and who probably shouldn't.

## Getting to know a new project

- [loomi-project-overview](../plugins/loomi-engagement/skills/loomi-project-overview/): what data an Engagement project holds.
- [engagement-report-explainer](../plugins/loomi-engagement/skills/engagement-report-explainer/): what the dashboards and reports you've inherited actually measure.
- Then [engagement-tracking-health](../plugins/loomi-engagement/skills/engagement-tracking-health/) and [data-feed-health](../plugins/loomi-platform/skills/data-feed-health/), so you know which numbers you can trust.

## Any other question

Ask it in your own words, for example *"how many people bought twice last month?"*. [ask-your-data](../plugins/loomi-engagement/skills/ask-your-data/) turns it into a query, checks the cost first, and shows you the query and assumptions with the answer.

## Good to know

- **Nearly every skill only reads data.** The few that can change things are marked **writes**. They only run when you call them by name, and they show you exactly what will change and wait for your "yes".
- **Discovery changes go live immediately**, so test big ranking changes with an A/B test first.
- **Impact figures are estimates.** Skills show their working and assumptions so you can sense-check them.
- **Data usually lags by about two days.** "Last 7 days" usually ends two days ago.
