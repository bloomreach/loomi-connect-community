# loomi-engagement

Skills for **Bloomreach Engagement** that use Loomi Connect.

### Data and setup

| Skill | What it does | Access |
|---|---|---|
| [loomi-project-overview](skills/loomi-project-overview/) | Summarises a project's customer data, events and good next questions | Read-only |
| [engagement-tracking-health](skills/engagement-tracking-health/) | Event volume drops, junk event types, property fill rates and type drift | Read-only |
| [ask-your-data](skills/ask-your-data/) | Answers plain-English analytics questions with cost-checked EQL, showing the query and assumptions | Read-only |
| [engagement-report-explainer](skills/engagement-report-explainer/) | Explains an inherited dashboard, report, funnel or segment in plain English; audits saved analyses | Read-only |
| [customer-360-lookup](skills/customer-360-lookup/) | Privacy-first summary of one named customer: profile, timeline, scores, recommendations and support flags | Read-only |
| [engagement-number-reconciliation](skills/engagement-number-reconciliation/) | Why two numbers that should match don't (AI answer vs report, segment vs filter, Bloomreach vs BI or ESP), and which one to use | Read-only |
| [portfolio-overview](skills/portfolio-overview/) | One health table across every Engagement project in an organisation, with flags and hand-offs | Read-only |
| [engagement-catalog-fixer](skills/engagement-catalog-fixer/) | Fixes Engagement catalog items (price, sale price, stock, URL, image, title) from catalog-parity-check findings or your list, with full-item undo; deletes only items you name | **Writes** |

### Campaigns and automation

| Skill | What it does | Access |
|---|---|---|
| [engagement-campaign-digest](skills/engagement-campaign-digest/) | Email and SMS performance digest compared with the previous period | Read-only |
| [deliverability-trend](skills/deliverability-trend/) | 90-day weekly email bounce, complaint and unsubscribe trend: guard-rail breaches, drift, spikes and where they come from | Read-only |
| [engagement-send-collision-check](skills/engagement-send-collision-check/) | Overlapping sends, busy days, channel clashes and missing frequency caps | Read-only |
| [contact-frequency-audit](skills/contact-frequency-audit/) | How often customers were really messaged per channel, opt-outs and clicks by frequency, and a recommended cap | Read-only |
| [engagement-scenario-explainer](skills/engagement-scenario-explainer/) | Explains a scenario in plain English; audit mode for stale or broken flows | Read-only |
| [engagement-scenario-builder](skills/engagement-scenario-builder/) | Builds or changes a scenario from a plain-English description, saved as a draft after confirmation | **Writes** |
| [engagement-ab-test-setup](skills/engagement-ab-test-setup/) | Sets up an A/B test or holdout in a scenario: sized, planned and added as a draft change after confirmation | **Writes** |
| [scenario-template-launcher](skills/scenario-template-launcher/) | Starts a new scenario by cloning a proven one from the same or another project as a draft, with a fix list of references that won't resolve | **Writes** |
| [convert-html-email-to-bloomreach](skills/convert-html-email-to-bloomreach/) | Migrates HTML email exports from any other ESP (Mailchimp, SFMC, HubSpot, Braze, Iterable, ActiveCampaign, plain HTML) into editable Visual Builder emails, saved as draft scenarios after confirmation | **Writes** |
| [convert-klaviyo-email-to-bloomreach](skills/convert-klaviyo-email-to-bloomreach/) | Migrates Klaviyo email exports into editable Visual Builder emails, saved as draft scenarios after confirmation | **Writes** |
| [engagement-email-builder](skills/engagement-email-builder/) | Turns a brief into an email campaign draft (subject, preheader, responsive HTML, personalization, existing sender and segment), linted, created after confirmation and never sent | **Writes** |
| [engagement-sms-builder](skills/engagement-sms-builder/) | Turns a brief into an SMS campaign draft, linted for segments, STOP/HELP, links, consent and quiet hours; can revise its own draft; never started or deleted | **Writes** |
| [engagement-scenario-performance](skills/engagement-scenario-performance/) | Step-by-step results for one scenario: sends, clicks, purchases after, split assignments | Read-only |
| [engagement-journey-health](skills/engagement-journey-health/) | All live flows at once: broken, not sending or suppressed (silent flows, steps mostly suppressed or failing, delivery drops, leftover conditions), one fix each | Read-only |
| [lifecycle-coverage-map](skills/lifecycle-coverage-map/) | Which of eight standard lifecycle flows are live, weak, stopped, draft or missing, with the monthly revenue at stake for each gap | Read-only |
| [engagement-jinja-writer](skills/engagement-jinja-writer/) | Writes and fixes Bloomreach Jinja for weblayers, emails and scenarios, checked against the rules that break templates, with real asset IDs looked up | Read-only |
| [engagement-weblayer-builder](skills/engagement-weblayer-builder/) | Builds, edits and fixes weblayer HTML, CSS and JavaScript on the platform skeleton, fully parameterised, reading the existing weblayer first | Read-only |
| [engagement-weblayer-qa](skills/engagement-weblayer-qa/) | Pre-launch GO / NO-GO check of one weblayer: skeleton, tracking, triggering code, unsafe code and loads, parameters, Jinja, links, closing and accessibility | Read-only |
| [scenario-qa](skills/scenario-qa/) | Pre-launch QA of one scenario's emails, SMS and push: links, Jinja, compliance and flow, with a go/no-go verdict | Read-only |
| [campaign-qa](skills/campaign-qa/) | Pre-send QA of one email or SMS campaign, every variant and translation: links, Jinja, compliance, spam risk, audience and schedule, with a go/no-go verdict | Read-only |
| [engagement-send-preflight](skills/engagement-send-preflight/) | Go/no-go list of every email, SMS and push due in the next few days, with what to fix before each one sends, plus collisions | Read-only |
| [voucher-pool-health](skills/voucher-pool-health/) | Voucher pools that will run out or expire before the sends that use them: days of cover, planned demand, empty pools still in live use, unused pools | Read-only |
| [onsite-experience-audit](skills/onsite-experience-audit/) | Expired, overlapping, untested or abandoned banners, weblayers and surveys | Read-only |
| [engagement-survey-insights](skills/engagement-survey-insights/) | Survey results from aggregate EQL: respondents, answer distributions, NPS-style and CSAT scores with confidence intervals, weekly trends and splits, and surveys or questions to fix; free text counted, never listed | Read-only |
| [engagement-experiment-readout](skills/engagement-experiment-readout/) | A/B test results for scenarios and campaigns: call a winner, keep running or stop | Read-only |
| [recommendation-model-audit](skills/recommendation-model-audit/) | Recommendation engines: usage, catalog freshness, duplicates, filters, and placements missing recommendations | Read-only |

### Audiences and revenue

| Skill | What it does | Access |
|---|---|---|
| [engagement-segment-builder](skills/engagement-segment-builder/) | Plain-English audience description to segment definition and size; can create it after confirmation | **Writes** |
| [funnel-leak-finder](skills/funnel-leak-finder/) | Where shoppers drop out between product view and purchase, abandoned-cart value, missing recovery flows | Read-only |
| [winback-opportunity](skills/winback-opportunity/) | Revenue at risk from lapsing customers, coverage gaps, and a win-back programme | Read-only |
| [engagement-revenue-change-explainer](skills/engagement-revenue-change-explainer/) | Why Engagement purchase revenue, orders or AOV changed between two periods: buyers (new vs returning) × orders per buyer × order value, then campaign drivers | Read-only |
| [engagement-repeat-purchase-cohorts](skills/engagement-repeat-purchase-cohorts/) | Repeat purchase rate by first-purchase month, time to second order, and when to send the second-purchase nudge | Read-only |
| [segment-opportunity-finder](skills/segment-opportunity-finder/) | Finds valuable audiences you haven't targeted yet, ranked by value and how many can be reached | Read-only |
| [contactability-audit](skills/contactability-audit/) | Share of customers reachable by email, SMS and push, consent trend, unreachable high-value customers and unused consent categories | Read-only |
| [ad-audience-sync-health](skills/ad-audience-sync-health/) | Ad-platform audience steps, external segments and autosegments that are stale, failing, tiny, duplicated, built on archived segments or missing advertising consent | Read-only |
| [prediction-activation-check](skills/prediction-activation-check/) | Predictions that are built but unused or stale, with ideas for putting them to work | Read-only |

### Housekeeping and governance

| Skill | What it does | Access |
|---|---|---|
| [engagement-asset-cleanup](skills/engagement-asset-cleanup/) | Archive, delete or review list of stale, test, duplicate and unused assets | Read-only |
| [project-access-review](skills/project-access-review/) | User-access review across projects: external, shared and test accounts, with removals to action | Read-only |
| [engagement-dependency-map](skills/engagement-dependency-map/) | What uses a definition, what breaks if it goes, and a safe deletion order | Read-only |
| [integration-inventory](skills/integration-inventory/) | Unused, duplicate, broken and secret-bearing integrations, API triggers, project variables and webhooks, without repeating secrets | Read-only |
| [engagement-media-cleanup](skills/engagement-media-cleanup/) | Unused, heavy, duplicate and alt-less images, blocks, snippets and templates, with fix, delete and review lists | Read-only |

Skills marked **Writes** only run when you call them by name, and ask for confirmation before every change.

To add a skill, see [CONTRIBUTING.md](../../CONTRIBUTING.md).
