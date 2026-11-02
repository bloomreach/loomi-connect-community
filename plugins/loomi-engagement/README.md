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

### Campaigns and automation

| Skill | What it does | Access |
|---|---|---|
| [engagement-campaign-digest](skills/engagement-campaign-digest/) | Email and SMS performance digest compared with the previous period | Read-only |
| [engagement-send-collision-check](skills/engagement-send-collision-check/) | Overlapping sends, busy days, channel clashes and missing frequency caps | Read-only |
| [engagement-scenario-explainer](skills/engagement-scenario-explainer/) | Explains a scenario in plain English; audit mode for stale or broken flows | Read-only |
| [engagement-scenario-builder](skills/engagement-scenario-builder/) | Builds or changes a scenario from a plain-English description, saved as a draft after confirmation | **Writes** |
| [convert-klaviyo-email-to-bloomreach](skills/convert-klaviyo-email-to-bloomreach/) | Migrates Klaviyo email exports into editable Visual Builder emails, saved as draft scenarios after confirmation | **Writes** |
| [engagement-scenario-performance](skills/engagement-scenario-performance/) | Step-by-step results for one scenario: sends, clicks, purchases after, split assignments | Read-only |
| [engagement-jinja-writer](skills/engagement-jinja-writer/) | Writes and fixes Bloomreach Jinja for weblayers, emails and scenarios, checked against the rules that break templates, with real asset IDs looked up | Read-only |
| [engagement-weblayer-builder](skills/engagement-weblayer-builder/) | Builds, edits and fixes weblayer HTML, CSS and JavaScript on the platform skeleton, fully parameterised, reading the existing weblayer first | Read-only |
| [scenario-qa](skills/scenario-qa/) | Pre-launch QA of one scenario's emails, SMS and push: links, Jinja, compliance and flow, with a go/no-go verdict | Read-only |
| [onsite-experience-audit](skills/onsite-experience-audit/) | Expired, overlapping, untested or abandoned banners, weblayers and surveys | Read-only |
| [engagement-experiment-readout](skills/engagement-experiment-readout/) | A/B test results for scenarios and campaigns: call a winner, keep running or stop | Read-only |
| [recommendation-model-audit](skills/recommendation-model-audit/) | Recommendation engines: usage, catalog freshness, duplicates, filters, and placements missing recommendations | Read-only |

### Audiences and revenue

| Skill | What it does | Access |
|---|---|---|
| [engagement-segment-builder](skills/engagement-segment-builder/) | Plain-English audience description to segment definition and size; can create it after confirmation | **Writes** |
| [funnel-leak-finder](skills/funnel-leak-finder/) | Where shoppers drop out between product view and purchase, abandoned-cart value, missing recovery flows | Read-only |
| [winback-opportunity](skills/winback-opportunity/) | Revenue at risk from lapsing customers, coverage gaps, and a win-back programme | Read-only |
| [segment-opportunity-finder](skills/segment-opportunity-finder/) | Finds valuable audiences you haven't targeted yet, ranked by value and how many can be reached | Read-only |
| [prediction-activation-check](skills/prediction-activation-check/) | Predictions that are built but unused or stale, with ideas for putting them to work | Read-only |

### Housekeeping and governance

| Skill | What it does | Access |
|---|---|---|
| [engagement-asset-cleanup](skills/engagement-asset-cleanup/) | Archive, delete or review list of stale, test, duplicate and unused assets | Read-only |
| [project-access-review](skills/project-access-review/) | User-access review across projects: external, shared and test accounts, with removals to action | Read-only |

Skills marked **Writes** only run when you call them by name, and ask for confirmation before every change.

To add a skill, see [CONTRIBUTING.md](../../CONTRIBUTING.md).
