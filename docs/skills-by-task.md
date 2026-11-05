# Skills by task

This guide is for merchandisers, ecommerce managers and CRM teams who run an online store on Bloomreach. It points you to the right skill for the job you're doing.

You don't need to remember skill names. Ask in your own words, for example *"how did search do last week?"*, and the assistant picks the right skill. The names below help you see what's possible, and let you call a skill directly when you want to.

Before you start, [connect Loomi Connect](connecting-loomi-connect.md) and install the plugins (see the [README](../README.md#install)).

## Every Monday

| Ask | Skill |
|---|---|
| "Give me the weekly briefing" | [weekly-ecommerce-briefing](../plugins/loomi-platform/skills/weekly-ecommerce-briefing/): KPIs, movers, marketing, health alerts and three things to do this week |
| "What are our top searches and categories, and which have problems?" | [weekly-ecommerce-briefing](../plugins/loomi-platform/skills/weekly-ecommerce-briefing/) for the weekly short list; [discovery-search-health](../plugins/loomi-discovery/skills/discovery-search-health/) and [discovery-category-health](../plugins/loomi-discovery/skills/discovery-category-health/) for the full picture |
| "What's trending in search?" | [discovery-trending-searches](../plugins/loomi-discovery/skills/discovery-trending-searches/) |
| "Put together our QBR" | [qbr-report](../plugins/loomi-platform/skills/qbr-report/) (quarterly): the quarter against last quarter and last year, wins, problems, tests run and next quarter's plays |
| "Which of our client or brand projects need attention?" | [portfolio-overview](../plugins/loomi-engagement/skills/portfolio-overview/): one health table across every Engagement project, with flagged projects handed to the right skill |
| "How did our emails and SMS do?" | [engagement-campaign-digest](../plugins/loomi-engagement/skills/engagement-campaign-digest/) |
| "Are our new products getting seen?" | [new-arrivals-tracker](../plugins/loomi-discovery/skills/new-arrivals-tracker/) |

## When something looks wrong

| Ask | Skill |
|---|---|
| "Why did revenue drop yesterday or last week?" | [revenue-anomaly-explainer](../plugins/loomi-platform/skills/revenue-anomaly-explainer/): a breakdown that adds up, with causes ranked by evidence |
| "Why did Engagement revenue double in July?" | [engagement-revenue-change-explainer](../plugins/loomi-engagement/skills/engagement-revenue-change-explainer/): Engagement purchase events split into buyers (new vs returning), orders per buyer and order value, with campaign drivers |
| "Is our data and tracking OK?" | [data-feed-health](../plugins/loomi-platform/skills/data-feed-health/) (pixel, feeds, Data Hub) and [engagement-tracking-health](../plugins/loomi-engagement/skills/engagement-tracking-health/) (events and properties) |
| "Why is this search performing badly?" | [discovery-query-diagnosis](../plugins/loomi-discovery/skills/discovery-query-diagnosis/) |
| "Why isn't this product showing for 'dress'?" | [discovery-product-visibility](../plugins/loomi-discovery/skills/discovery-product-visibility/): where it ranks or why it's missing, and the smallest fix |
| "How is this product doing?" | [discovery-product-report](../plugins/loomi-discovery/skills/discovery-product-report/): performance against peers, where it ranks, rules and stock, with next actions |
| "Are any of our top products out of stock but still on page one?" | [discovery-variant-health](../plugins/loomi-discovery/skills/discovery-variant-health/): stock, price, SKU and image problems on page-one products and top sellers |
| "Is our catalog set up right?" / "Is margin exposed in search?" | [discovery-catalog-config-audit](../plugins/loomi-discovery/skills/discovery-catalog-config-audit/): attribute and index settings, with a prioritised fix list |
| "Why does searching 'dresses' show different products from the dresses page?" | [discovery-search-category-match](../plugins/loomi-discovery/skills/discovery-search-category-match/): search vs category page one, with a redirect or ranking recommendation |
| "Is search down?" / "Are we within our MUV contract?" | [discovery-api-health](../plugins/loomi-discovery/skills/discovery-api-health/): API volume, errors and unique visitors against contract |
| "Where are shoppers dropping out?" | [funnel-leak-finder](../plugins/loomi-engagement/skills/funnel-leak-finder/) |
| "Is our email deliverability getting worse?" | [deliverability-trend](../plugins/loomi-engagement/skills/deliverability-trend/): weekly bounce, complaint and unsubscribe trend, with where the problems come from |
| "Do our Discovery and Engagement catalogs match?" | [catalog-parity-check](../plugins/loomi-platform/skills/catalog-parity-check/): missing products and price, stock and URL mismatches, with rates and revenue at stake |
| "Fix the price and stock mismatches in our Engagement catalog" | [engagement-catalog-fixer](../plugins/loomi-engagement/skills/engagement-catalog-fixer/) (**writes** catalog items, after you confirm) |
| "Audit our Data Hub item collections" | [datahub-collection-audit](../plugins/loomi-platform/skills/datahub-collection-audit/): collection drift, field fill rates, type mismatches and stale jobs, with an owner per fix |
| "Do our retention rules break any segments or reports?" | [data-retention-review](../plugins/loomi-platform/skills/data-retention-review/): windows longer than retention, over-kept events, personal properties |
| "A customer has a problem. What do we know about them?" | [customer-360-lookup](../plugins/loomi-engagement/skills/customer-360-lookup/): one customer's profile, recent activity and support flags, with personal data kept to a minimum |
| "Why does the AI say 12,000 and our report 6,000? Which is right?" | [engagement-number-reconciliation](../plugins/loomi-engagement/skills/engagement-number-reconciliation/): both definitions side by side, the cause, and which number answers your question |

## Improving search

Start with the health check, then go deeper where it points you.

1. [discovery-search-health](../plugins/loomi-discovery/skills/discovery-search-health/): overall search performance, and the queries worth investigating.
2. [discovery-zero-results-triage](../plugins/loomi-discovery/skills/discovery-zero-results-triage/): every search that leads nowhere, sorted into synonym fix, catalog gap, redirect or noise.
3. [discovery-query-diagnosis](../plugins/loomi-discovery/skills/discovery-query-diagnosis/): a deep dive into one query, with fixes ranked by impact.
4. [discovery-query-rule-impact](../plugins/loomi-discovery/skills/discovery-query-rule-impact/): what each merchandising rule on one search does, and whether it helps or hurts revenue.
5. [discovery-synonym-review](../plugins/loomi-discovery/skills/discovery-synonym-review/): synonyms that are bad, risky or missing a direction.
6. [autosuggest-audit](../plugins/loomi-discovery/skills/autosuggest-audit/): search suggestions that steer shoppers wrong, or leave out what sells.
7. [facet-optimizer](../plugins/loomi-discovery/skills/facet-optimizer/): filters that are missing, messy or unhelpful.
8. [facet-rule-fixer](../plugins/loomi-discovery/skills/facet-rule-fixer/) (**writes** facet rules, after you confirm): apply the filter changes the optimizer recommends.
9. [discovery-redirect-audit](../plugins/loomi-discovery/skills/discovery-redirect-audit/): redirects that are broken, clash with each other, hijack broad searches, or are missing.

## Improving categories, products and brands

| Ask | Skill |
|---|---|
| "Which categories are underperforming?" | [discovery-category-health](../plugins/loomi-discovery/skills/discovery-category-health/) |
| "Which products should I boost, fix or clear?" | [product-opportunity-finder](../plugins/loomi-discovery/skills/product-opportunity-finder/) |
| "How are our brands doing? I have a supplier meeting." | [brand-performance-review](../plugins/loomi-discovery/skills/brand-performance-review/) |
| "What new collections should we create?" | [collection-suggester](../plugins/loomi-platform/skills/collection-suggester/) |
| "Build a pickleball collection" or "Which products belong with this search?" | [topic-collection-builder](../plugins/loomi-discovery/skills/topic-collection-builder/) |
| "Clean up our merchandising rules" | [discovery-rule-audit](../plugins/loomi-discovery/skills/discovery-rule-audit/) |
| "Is this ranking rule / synonym / redirect safe to switch on?" | [discovery-change-qa](../plugins/loomi-discovery/skills/discovery-change-qa/): before/after preview, revenue at stake and clashes, with a go/no-go verdict |
| "Which ranking algorithms are we using, and are any broken?" | [discovery-ranking-algorithm-review](../plugins/loomi-discovery/skills/discovery-ranking-algorithm-review/): where each algorithm is used, status, weights and clean-up, prioritised |
| "Retire the unused ranking algorithm" / "Lower the margin weight on our algorithm" | [discovery-ranking-algorithm-fixer](../plugins/loomi-discovery/skills/discovery-ranking-algorithm-fixer/) (**writes** algorithms, after you confirm): re-weights, copies, renames or retires Ranking Studio algorithms |
| "Why do some shoppers see different results?" / "Clean up our audiences" | [discovery-hidden-config-audit](../plugins/loomi-discovery/skills/discovery-hidden-config-audit/): broken or unused audiences, personalised rules, forgotten API parameter overrides |
| "Which of our banners are unused or broken?" | [discovery-media-asset-cleanup](../plugins/loomi-discovery/skills/discovery-media-asset-cleanup/): asset library against the media rules that use it, with a cleanup list |
| "Apply the synonym fixes" / "Add a synonym for t-shirt" | [discovery-synonym-fixer](../plugins/loomi-discovery/skills/discovery-synonym-fixer/) (**writes** synonyms, after you confirm) |
| "Fix the redirects the audit found" / "Add a redirect for 'track order'" | [discovery-redirect-fixer](../plugins/loomi-discovery/skills/discovery-redirect-fixer/) (**writes** redirects, after you confirm) |
| "Apply the rule audit's clean-up list" | [discovery-rule-cleanup](../plugins/loomi-discovery/skills/discovery-rule-cleanup/) (**writes** rule changes and deletes, after you confirm) |
| "Stop autosuggest showing 'dress fabric'" / "Apply the autosuggest audit's exclusions" | [discovery-autosuggest-exclusions](../plugins/loomi-discovery/skills/discovery-autosuggest-exclusions/) (**writes** exclusion rules, after you confirm) |
| "Are our dynamic categories working?" | [discovery-dynamic-category-review](../plugins/loomi-discovery/skills/discovery-dynamic-category-review/) |
| "Are our product recommendations set up well?" | [recommendation-model-audit](../plugins/loomi-engagement/skills/recommendation-model-audit/) |
| "Which products have weak data for Google and AI search?" | [product-data-audit](../plugins/loomi-product-data/skills/product-data-audit/) |
| "Improve the titles, descriptions and attributes for these products" | [product-data-enhancer](../plugins/loomi-product-data/skills/product-data-enhancer/): looks at the product images as well as the data, and suggests changes for you to review |
| "Find wrong prices in our catalog" | [price-anomaly-finder](../plugins/loomi-product-data/skills/price-anomaly-finder/): catalog-wide price outliers, unit errors and sale-price mistakes, ranked by exposure |
| "Our colour filter shows navy three times" | [attribute-normaliser](../plugins/loomi-product-data/skills/attribute-normaliser/): clusters messy attribute values and writes a mapping file for the feed team |

## Testing changes and checking they worked

1. [discovery-experiment-setup](../plugins/loomi-discovery/skills/discovery-experiment-setup/) (**writes**, after you confirm): set up an A/B test for a ranking change, or one ranking algorithm against another, with a preview first.
   For an A/B test or holdout inside an Engagement scenario, use [engagement-ab-test-setup](../plugins/loomi-engagement/skills/engagement-ab-test-setup/) (**writes**: adds the split to a draft or stopped flow, after you confirm).
2. [discovery-experiment-readout](../plugins/loomi-discovery/skills/discovery-experiment-readout/): what the test showed. Ship it, keep running, or stop.
   For A/B tests in Engagement scenarios and campaigns, use [engagement-experiment-readout](../plugins/loomi-engagement/skills/engagement-experiment-readout/).
3. [discovery-experiment-close](../plugins/loomi-discovery/skills/discovery-experiment-close/) (**writes**: ends the test and switches rules, after you confirm each step): ship the winner or keep today's behaviour, then archive.
4. [change-impact-tracker](../plugins/loomi-platform/skills/change-impact-tracker/): "Did my change work?" Before vs after, adjusted for the site-wide trend, for changes made outside a test.

## Playbooks: find, fix, test and measure in one run

A playbook runs several of the skills on this page in order and carries the results between them in a hand-off file, so you can stop and pick up again when a test or a flow has had time to run. Keep the hand-off files in one folder and start each week with the weekly triage.

| Ask | Skill |
|---|---|
| "What should we work on this week?" | [playbook-weekly-triage](../plugins/loomi-playbooks/skills/playbook-weekly-triage/) (read-only): lists due read-outs, confirms and re-checks across runs, builds the briefing, explains a big change, and hands up to three problems to playbooks |
| "Close the quarter and show what our changes earned" | [playbook-quarter-close](../plugins/loomi-playbooks/skills/playbook-quarter-close/) (read-only): lists the quarter's changes from hand-off files, measures the unconfirmed ones, builds the QBR and next quarter's campaign plan |
| "We've just started with a new customer: what do we fix first?" | [playbook-new-project](../plugins/loomi-playbooks/skills/playbook-new-project/) (read-only): runs the readiness, tracking, feed, catalog and lifecycle checks and writes a 30-day plan |
| "Which rule on 'black dress' is costing us money? Test a fix and roll it out if it wins." | [playbook-test-and-learn](../plugins/loomi-playbooks/skills/playbook-test-and-learn/) (**writes** through its test and close stages, after you confirm each step): rule impact, then A/B test, read-out, close and a check that it holds |
| "Too many searches find nothing: fix it properly" | [playbook-findability](../plugins/loomi-playbooks/skills/playbook-findability/) (**writes** through its synonyms stage, after you confirm each step): triage, data and config fixes for people, synonyms, recheck |
| "Do searches for our category names land as well as the category pages?" | [playbook-search-vs-category](../plugins/loomi-playbooks/skills/playbook-search-vs-category/) (**writes** through its fix stage, after you confirm each step): compare, redirect the worst one, measure it |
| "Which products are hidden gems? Test boosting the best one." | [playbook-product-opportunity](../plugins/loomi-playbooks/skills/playbook-product-opportunity/) (**writes** through its test and close stages, after you confirm each step): product opportunities, a product report, listing suggestions or an A/B test, read-out, close and a check that it holds |
| "Prepare our supplier meeting: would boosting this brand pay?" | [playbook-supplier-review](../plugins/loomi-playbooks/skills/playbook-supplier-review/) (**writes** through its test and close stages, after you confirm each step): scorecard, boost test, talking points |
| "'capris' searches return nothing and keep growing. Fix the search and email the people who searched." | [playbook-search-demand-to-revenue](../plugins/loomi-playbooks/skills/playbook-search-demand-to-revenue/) (**writes** through its fix and campaign stages, after you confirm each step): trending searches, zero-results triage, a synonym or landing collection, a campaign draft, the digest and a before-and-after check |
| "Our emails show prices and stock that don't match the site. Find what's out of sync and fix it." | [playbook-catalog-truth](../plugins/loomi-playbooks/skills/playbook-catalog-truth/) (**writes** through its fix stage, after you confirm each batch): catalog parity, price anomalies, variant health, Engagement catalog fixes and a recheck |
| "Revenue dropped 20% last week. Find out why and fix it." | [playbook-revenue-drop](../plugins/loomi-playbooks/skills/playbook-revenue-drop/) (**writes** through its rollback stage, after you confirm each step): revenue breakdown, feed, API, journey and change checks, a rule rollback and a recovery check |
| "Get us ready for Black Friday, then tell us how it went." | [playbook-peak-event](../plugins/loomi-playbooks/skills/playbook-peak-event/) (read-only): campaign plan, landing collections, readiness, voucher, preflight and collision checks, and a post-event revenue review |
| "Run this month's hygiene sweep" | [playbook-monthly-hygiene](../plugins/loomi-playbooks/skills/playbook-monthly-hygiene/) (**writes** through its rule-cleanup and redirect-fix stages, after you confirm each step): rules, redirects, then what's safe to delete in Engagement |
| "We have no browse abandonment flow: get one live and tell me what it makes" | [playbook-lifecycle-gap](../plugins/loomi-playbooks/skills/playbook-lifecycle-gap/) (**writes** through its launch and adapt stages, after you confirm each step): finds the gap, clones and fixes a draft, QAs it, then checks and measures it after you switch it on |
| "Build this campaign from the brief, check it, and tell me how it did" | [playbook-brief-to-results](../plugins/loomi-playbooks/skills/playbook-brief-to-results/) (**writes** through its build-email and build-sms stages, after you confirm each step): brief to draft, QA, preflight and clash check once scheduled, then the digest |
| "Our complaints and bounces are rising: fix it" | [playbook-deliverability-recovery](../plugins/loomi-playbooks/skills/playbook-deliverability-recovery/) (**writes** through its launch and adapt stages, after you confirm each step): trend, frequency and reach audits, a sunset or re-permission flow, then a recheck |
| "Put our unused churn model to work" | [playbook-prediction-activation](../plugins/loomi-playbooks/skills/playbook-prediction-activation/) (**writes** through its segment, launch and adapt stages, after you confirm each step): unused prediction to segment to live flow, then measured |
| "Win back our lapsed customers and show me it worked" | [playbook-lapsed-customers](../plugins/loomi-playbooks/skills/playbook-lapsed-customers/) (**writes** through its segment, launch and adapt stages, after you confirm each step): revenue at risk to audience to win-back flow, then reactivation measured |
| "Why is 'black boots' bad? Fix it" | [playbook-fix-one-search](../plugins/loomi-playbooks/skills/playbook-fix-one-search/) (**writes** through its synonyms and redirect stages, after you confirm each step): diagnose the search, check the fix, make it, measure it |
| "Our filters are a mess, fix them" | [playbook-facet-tune-up](../plugins/loomi-playbooks/skills/playbook-facet-tune-up/) (**writes** through its fix stage, after you confirm each step): review facets, check, apply, measure |
| "Tune up our category pages and collections" | [playbook-category-tune-up](../plugins/loomi-playbooks/skills/playbook-category-tune-up/) (read-only; you make the changes in the dashboard): category health, dynamic categories, new collections, measure |
| "Autosuggest offers junk, clean it up" | [playbook-autosuggest-cleanup](../plugins/loomi-playbooks/skills/playbook-autosuggest-cleanup/) (**writes** through its exclude stage, after you confirm each step): audit, exclude, re-audit |
| "Our search algorithm leans almost entirely on margin. Fix it, but test it first." | [playbook-ranking-algorithm-tune-up](../plugins/loomi-playbooks/skills/playbook-ranking-algorithm-tune-up/) (**writes** through its copy, test and close stages, after you confirm each step): algorithm review, corrected copy, A/B test, read-out, close and a check that it holds |
| "Get more first-time buyers to buy a second time" | [playbook-second-purchase](../plugins/loomi-playbooks/skills/playbook-second-purchase/) (**writes** through its launch, adapt and test stages, after you confirm each step): cohort baseline, a post-purchase flow timed to it, and a recheck of the repeat rate |
| "What should we A/B test on site?" | [playbook-onsite-test](../plugins/loomi-playbooks/skills/playbook-onsite-test/) (read-only): find a weblayer worth testing, write and QA the challenger, read the result after you launch it |
| "Grow the customers we're allowed to contact" | [playbook-reachable-audience](../plugins/loomi-playbooks/skills/playbook-reachable-audience/) (read-only): reach and consent audit, an on-site capture form built, QA'd and A/B tested after you launch it, then reach measured again |
| "Follow up our NPS detractors" | [playbook-voice-of-customer](../plugins/loomi-playbooks/skills/playbook-voice-of-customer/) (**writes** through its segment, flow, test and email stages, after you confirm each step): survey read-out, a detractor audience, a follow-up flow or email, then the score again |
| "Migrate this client from Klaviyo" | [playbook-migrate-from-klaviyo](../plugins/loomi-playbooks/skills/playbook-migrate-from-klaviyo/) (**writes** through its convert, launch and adapt stages, after you confirm each step): emails converted to draft scenarios and QA'd, then the missing flows mapped and the first one rebuilt |
| "Run our quarterly governance / access and integrations review" | [playbook-governance-review](../plugins/loomi-playbooks/skills/playbook-governance-review/) (read-only): access, integrations, retention, Data Hub, ad-audience consent and hidden Discovery settings in one pass, ending with findings and owners |
| "Which of our client projects need attention, and what do we run on each?" | [playbook-agency-portfolio](../plugins/loomi-playbooks/skills/playbook-agency-portfolio/) (read-only): portfolio health table, deeper check on the weakest, and a playbook to start or resume per project |

## Planning marketing

| Ask | Skill |
|---|---|
| "What campaigns should we run in the next 6–8 weeks?" | [campaign-planner](../plugins/loomi-platform/skills/campaign-planner/): retail calendar (default markets US, UK and EU), last year's results and current demand |
| "Which audiences should we be targeting?" | [segment-opportunity-finder](../plugins/loomi-engagement/skills/segment-opportunity-finder/) |
| "How many of our customers can we actually email?" | [contactability-audit](../plugins/loomi-engagement/skills/contactability-audit/): reach by channel, consent trend, unreachable high-value customers |
| "Which lifecycle flows are we missing?" | [lifecycle-coverage-map](../plugins/loomi-engagement/skills/lifecycle-coverage-map/): which standard flows exist and are live, and what each gap is worth |
| "Copy the browse abandonment flow from our other project" | [scenario-template-launcher](../plugins/loomi-engagement/skills/scenario-template-launcher/) (**writes** a draft, after you confirm): clones a proven scenario and lists what to fix |
| "How much revenue are we losing from lapsed customers?" | [winback-opportunity](../plugins/loomi-engagement/skills/winback-opportunity/) |
| "How many first-time buyers come back, and when?" | [engagement-repeat-purchase-cohorts](../plugins/loomi-engagement/skills/engagement-repeat-purchase-cohorts/) |
| "Build me a segment of…" | [engagement-segment-builder](../plugins/loomi-engagement/skills/engagement-segment-builder/) (**writes**, after you confirm) |
| "Set up a flow that…" / "Change the wait in our welcome series" | [engagement-scenario-builder](../plugins/loomi-engagement/skills/engagement-scenario-builder/) (**writes** a draft, after you confirm) |
| "Move our Klaviyo emails into Bloomreach" | [convert-klaviyo-email-to-bloomreach](../plugins/loomi-engagement/skills/convert-klaviyo-email-to-bloomreach/) (**writes** drafts and uploads images, after you confirm) |
| "Write a Black Friday email for our lapsed VIPs" | [engagement-email-builder](../plugins/loomi-engagement/skills/engagement-email-builder/) (**writes** a draft, after you confirm) |
| "Write a text for our lapsed VIPs: 20% off boots this weekend" | [engagement-sms-builder](../plugins/loomi-engagement/skills/engagement-sms-builder/) (**writes** a draft, or revises its own, after you confirm) |
| "How is our abandoned cart flow doing?" | [engagement-scenario-performance](../plugins/loomi-engagement/skills/engagement-scenario-performance/) |
| "Which of our live journeys are broken right now?" | [engagement-journey-health](../plugins/loomi-engagement/skills/engagement-journey-health/): all live flows at once: broken, not sending, suppressed |
| "Write the Jinja for a recommendations block" / "Why won't this Jinja save?" | [engagement-jinja-writer](../plugins/loomi-engagement/skills/engagement-jinja-writer/): personalization, recommendations, cart items and social proof for weblayers, emails and scenarios |
| "Build me a newsletter pop-up" / "Why isn't our weblayer showing?" | [engagement-weblayer-builder](../plugins/loomi-engagement/skills/engagement-weblayer-builder/): pop-ups, banners and inline weblayers, with dynamic data from engagement-jinja-writer |
| "Is our new pop-up ready to go live?" | [engagement-weblayer-qa](../plugins/loomi-engagement/skills/engagement-weblayer-qa/): skeleton, tracking, triggering code, links and accessibility for one weblayer, with a go/no-go verdict |
| "Is our welcome journey ready to go live?" | [scenario-qa](../plugins/loomi-engagement/skills/scenario-qa/): links, personalization and compliance in every send, with a go/no-go verdict |
| "Is the Black Friday email ready to send?" | [campaign-qa](../plugins/loomi-engagement/skills/campaign-qa/): every variant of one email or SMS campaign, with a go/no-go verdict |
| "What's going out this week, and is it ready?" | [engagement-send-preflight](../plugins/loomi-engagement/skills/engagement-send-preflight/): every send due in the next few days, with a go/no-go for each |
| "Turn what people search for into a campaign" | [search-demand-to-campaign](../plugins/loomi-platform/skills/search-demand-to-campaign/) (**writes** a draft, after you confirm) |
| "Are we sending too much to the same people?" | [engagement-send-collision-check](../plugins/loomi-engagement/skills/engagement-send-collision-check/) |
| "Are customers getting too many emails or texts?" | [contact-frequency-audit](../plugins/loomi-engagement/skills/contact-frequency-audit/): messages actually received per customer, fatigue by frequency and a recommended cap |
| "How is our NPS survey doing?" | [engagement-survey-insights](../plugins/loomi-engagement/skills/engagement-survey-insights/): survey answers, NPS and CSAT with confidence, trends and flags |
| "Will our voucher codes run out before Black Friday?" | [voucher-pool-health](../plugins/loomi-engagement/skills/voucher-pool-health/): days of cover per pool, empty or expiring pools still in use |
| "Are our Facebook and Google audiences healthy?" | [ad-audience-sync-health](../plugins/loomi-engagement/skills/ad-audience-sync-health/): stale, tiny, duplicated or unconsented ad audiences, and failed or unused autosegments |
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
- [engagement-dependency-map](../plugins/loomi-engagement/skills/engagement-dependency-map/): what uses each item on the cleanup list, and the order to delete them safely.
- [integration-inventory](../plugins/loomi-engagement/skills/integration-inventory/): unused, duplicate and broken integrations, API triggers and project variables, and keys stored where they shouldn't be.
- [engagement-media-cleanup](../plugins/loomi-engagement/skills/engagement-media-cleanup/): unused, oversized and duplicate images, blocks, snippets and templates, and images missing alt text.
- [project-access-review](../plugins/loomi-engagement/skills/project-access-review/) (quarterly): who has access to each project, and who probably shouldn't.

## Getting to know a new project

- [loomi-project-overview](../plugins/loomi-engagement/skills/loomi-project-overview/): what data an Engagement project holds.
- [implementation-readiness](../plugins/loomi-platform/skills/implementation-readiness/): for a new account, a go-live checklist with blockers first and an owner for each fix.
- [engagement-report-explainer](../plugins/loomi-engagement/skills/engagement-report-explainer/): what the dashboards and reports you've inherited actually measure.
- Then [engagement-tracking-health](../plugins/loomi-engagement/skills/engagement-tracking-health/) and [data-feed-health](../plugins/loomi-platform/skills/data-feed-health/), so you know which numbers you can trust.

## Any other question

Ask it in your own words, for example *"how many people bought twice last month?"*. [ask-your-data](../plugins/loomi-engagement/skills/ask-your-data/) turns it into a query, checks the cost first, and shows you the query and assumptions with the answer.

## When a Loomi Connect tool misbehaves

[loomi-connect-feedback](../plugins/loomi-platform/skills/loomi-connect-feedback/) (**writes** one report, after you confirm) turns the problem, or a "(bug?)" item in [known-tool-behaviour.md](known-tool-behaviour.md), into one redacted report for the Loomi Connect team.

## Good to know

- **Nearly every skill only reads data.** The few that can change things are marked **writes**. They only run when you call them by name, and they show you exactly what will change and wait for your "yes".
- **Discovery changes go live immediately**, so test big ranking changes with an A/B test first.
- **Impact figures are estimates.** Skills show their working and assumptions so you can sense-check them.
- **Data usually lags by about two days.** "Last 7 days" usually ends two days ago.
