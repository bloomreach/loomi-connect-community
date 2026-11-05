# Engagement A/B test setup

Sets up an A/B test or holdout inside a Bloomreach Engagement scenario: two versions of a message, sending against a holdout that gets nothing, or two wait times before a step. It agrees the primary metric, sizes the test (customers per branch and days), plans an A/B split step with its branches, and adds it to a draft or stopped flow, or to a new draft copy of a running one, only after an explicit "yes". It never switches a flow on; `engagement-experiment-readout` reads the result once the test has run.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | **Writes**: adds an A/B split (and variant B's step) to a draft or inactive scenario with `update_scenario`, or, for a running scenario when the user asks, creates a new draft copy with the split with `create_scenario`. One write per test, after explicit confirmation. Never starts, stops or deletes a flow, and never edits a running one |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `search_scenarios`, `search_scenario_nodes`*, `get_guide`, `update_scenario`*, `create_scenario` (* found with `search_tools` and run with `call_tool` when not listed) |
| **Other requirements** | Python 3 for `scripts/ab_split_plan.py` and `scripts/ab_test_duration.py` (standard library only); the steps also work by hand |
| **Tested with** | Claude Code: script tests with synthetic scenarios; tool names and arguments checked against the live schemas and a read of demo scenarios. **The writes are untested**: no scenario was changed |
| **Maintainer** | @bloomreach |

## Example prompts

- "A/B test a 10% discount in the cart reminder email of our abandoned cart flow."
- "Hold out 10% of customers from the win-back journey so we can see if it works."
- "Does sending the reminder after 24 hours beat 4 hours? Set up the test."
- "How long would an A/B test on the welcome email need to run?"

See [examples/cart-reminder-discount.md](examples/cart-reminder-discount.md).

## How it works

1. Finds the scenario and shows its steps; you pick the connection to split on.
2. Agrees the test type, branch names and shares, variant B's message (a copy you edit in Engagement, or an existing message step), and the primary metric.
3. `scripts/ab_test_duration.py` sizes it from how many customers reach that step and today's rate (two-proportion formula, uneven splits supported), in whole weeks.
4. `scripts/ab_split_plan.py plan` builds the full scenario payload with the `ab-split` node and its connections, blocks unsafe plans (running flow, missing message designs, wrong step type, bad shares) and keeps an undo. The test spec format is in [references/test-spec.md](references/test-spec.md); thresholds in [references/rules.json](references/rules.json).
5. After a yes, it re-checks the flow hasn't changed, writes, reads it back and verifies with `ab_split_plan.py verify`.

## Notes and limitations

- Only the `ab-split` node is built: its shape was read from saved scenarios. Personalised (`ab-split-contextual`) and auto-winner splits, and segment forks, aren't verified, so they're out of scope.
- Two branches per split. A message test's variant B starts as a copy of the control: edit its content in Engagement before switching the flow on.
- Standalone email campaign A/B tests are out of scope. The `email-template-best-practices` guide documents a `manual` split for `create_email_campaign`, but it's untested here and building email content is another job; `update_email_campaign` collapses an A/B campaign's split.
- Flow-level settings (conversion goal, description) aren't kept by the write tools; the metric goes in the plan and the hand-over for the readout.
- Implicit invocation is turned off for OpenAI clients (`agents/openai.yaml`), because this skill writes.
