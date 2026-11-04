# Engagement survey insights

Turns Bloomreach Engagement surveys into insight. It lists a project's surveys and reads each one's questions, then measures answers with aggregate EQL on the `survey` event:

- respondents, and the response and close rate when the user can say who saw or was sent the survey;
- the answered share of every question, and drop-off from the first question to the last;
- answer distributions for choice and rating questions, with an interval on each share;
- NPS-style scores and CSAT, each with the sample size, a confidence interval and a note when the sample is small (Engagement's 10-star rating runs 1 to 10, so the score is labelled NPS-style);
- weekly trends of responses and of one score;
- splits by a low-cardinality, non-personal property such as device or country, when asked;
- flags for surveys with too few responses to trust, active surveys nobody answers, surveys not edited for a long time, questions everybody skips, many typed-in Other answers and a drop in responses.

Free-text answers are counted, never listed. Only on explicit request, after explaining the privacy trade-off, it summarises themes from a small capped sample of the most repeated answers, without quoting any. It never reads individual customers and never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_surveys`, `get_event_schema`, `estimate_eql_cost`, `execute_analytics_eql`, optionally `get_customer_property_schema`, `search_email_campaigns`, `search_sms_campaigns`, `search_banners` |
| **Other requirements** | None. Python 3 is optional, for the bundled script |
| **Tested with** | Claude Code (manual read-only run, November 2026, on two demo projects): survey list and three survey details read (single-choice with Other, 5- and 10-star ratings, text field); the `survey` event schema checked; respondents, a per-question count, an answer distribution, a daily trend, a day-by-answer cross-tab and a promoter split by property run as aggregate EQL with their cost ratings recorded. The response-rate denominators and the free-text theme query weren't run. `scripts/survey_insights.py` tested on synthetic fixtures. Not tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "How is our post-purchase NPS survey doing?"
- "What did people answer in the returns survey last quarter?"
- "Show me CSAT by week for the checkout survey, and split it by device."
- "Which of our surveys have too few answers to trust?"

See [examples/illustrative-survey-insights.md](examples/illustrative-survey-insights.md) for an example output. Its names and numbers are invented.

## How it works

1. **Surveys:** `search_surveys` lists them, and by `survey_id` returns each one's questions (type, choices, star count, mandatory).
2. **Event check:** `get_event_schema` shows which properties the project's `survey` event carries (`survey_id` and `question_index` where documented; some projects only have `question` and `answer`), which decides the EQL filter.
3. **Counts:** aggregate EQL only, estimated first. [references/eql-patterns.md](references/eql-patterns.md) has every query and its tested status.
4. **Numbers:** [scripts/survey_insights.py](scripts/survey_insights.py) (standard library only, no network) works out rates, distributions, NPS and CSAT with intervals, weekly trends, splits and flags. Thresholds live in [references/rules.json](references/rules.json); [references/scoring.md](references/scoring.md) has the same maths by hand.

It hands off to `onsite-experience-audit` (survey hygiene), `engagement-segment-builder` and `segment-opportunity-finder` (follow up detractors or unhappy customers), `funnel-leak-finder` (when answers point at a journey step) and `engagement-tracking-health` (missing or falling survey events).

## Notes and limitations

- Engagement surveys are standalone pages reached through a personalised link, so there's no "shown" event of their own. A response rate needs a denominator from the email, SMS or weblayer that carries the link; without one, the skill reports respondents only.
- Answers are stored as strings, and the survey detail's question `id` isn't the `question_index` in the data: the skill uses the question's position.
- Customer counts are cheap (`medium`); event breakdowns are `high` over 90 days and `very_high` over a year on a mid-sized project, so long windows are skipped.
- A split uses the customer's current property value, not the value when they answered.
- Free-text themes come from the most repeated answers only, so one-off answers are missed.
