# Engagement segment builder

Turns a plain-English audience description, such as "customers who bought in the last 90 days but not in the last 30, with email consent", into a Bloomreach Engagement segment definition. It maps the words to the project's real properties, events and consent categories, and reuses existing segmentations and filters where it can. It estimates the audience size with an aggregate EQL count, checking the cost first, and gives step-by-step build instructions for the UI. If the user asks, it can create the customer filter or segmentation, after showing the exact definition and getting an explicit "yes".

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: can create one customer filter (`create_customer_filter`) or one segmentation (`create_segmentation`), only after explicit confirmation. It never updates or deletes anything |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_customer_property_schema`, `get_event_schema`, `get_customer_schema`, `get_consent_settings`*, `search_segmentations`, `search_customer_filters`, `search_aggregates`, `search_predictions`, `estimate_eql_cost`, `execute_analytics_eql`, `create_customer_filter`*, `create_segmentation`* (* found with `search_tools` and run with `call_tool`) |
| **Tested with** | Claude Code: live, read-only run against a sandbox project (schema mapping, consent lookup, reuse search, EQL parsing and cost checks, aggregate counts). The create tools were **not** called in testing. Not yet tested in an OpenAI client |
| **Maintainer** | Bloomreach |

## Example prompts

- "Build a segment of customers who bought in the last 90 days but not the last 30, with email consent."
- "How many US customers have bought at least twice this year?"
- "Define an audience of people who viewed a product over $100 but never purchased, and create it as a customer filter."

See [examples/lapsing-buyers.md](examples/lapsing-buyers.md) for illustrative output.

## Notes and limitations

- The EQL cost estimator doesn't check names, so the skill checks every property and event against the schema first.
- On large projects, even simple customer counts can be rated "high" cost. The skill asks before running those, and never runs "very high" ones.
- Analytics queries share a rate limit of about one every 3 seconds per Engagement instance.
- The exact filter-atom shapes for relative date windows and consent weren't confirmed in testing. The skill only offers to create a filter when it can copy every kind of condition from an existing filter or segmentation in the project. Otherwise it gives UI steps instead.
- [scripts/filter_to_eql.py](scripts/filter_to_eql.py) (standard library, no network) translates a saved customer filter, or a scenario condition, into the EQL condition and count query used to size it, and names the rules EQL can't count. loomi-connect-openui uses the same rules; [tests/fixtures/engagement/segment_builder/contract/](../../../../tests/fixtures/engagement/segment_builder/contract/) keeps them in step.
- The `loomi://guides/*` resources (EQL and segmentation guides) weren't readable from the test client. The EQL patterns in [references/eql-patterns.md](references/eql-patterns.md) come from the tool documentation and live testing.
