# Playbook: new arrivals launch

Makes sure new products get seen and sold, not just added. Nine existing skills run in order: find the new products that aren't being seen or aren't selling, explain why a buried one ranks low, A/B test a boost on its page, build an audience with an affinity for its category and a "new in" email draft, QA it, read the test, roll out the winner, and measure both the boost and the email. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up when the test has run and the email has gone out.

| | |
|---|---|
| **Products** | Discovery and Engagement (either alone works: without Engagement there's no email; without Discovery, you name the new products and there's no boost test) |
| **Access** | **Writes**, through its stage skills only: `discovery-experiment-setup` creates a ranking rule (or variant) and an A/B test and starts it, and switches off a rule or variant it created if a later step fails; `engagement-segment-builder` creates one customer filter or segmentation; `engagement-email-builder` creates one email campaign draft, which sends nothing until a person starts it; `discovery-experiment-close` ends the test (live at once, can't be undone), fixes a rule left in the wrong state and archives it. Each write only after its own explicit "yes". This playbook never schedules or sends, and never deletes |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_ranking_rule`, `create_ranking_rule_variant`, `update_ranking_rule`, `create_discovery_experiment`, `start_discovery_experiment`, `create_customer_filter`, `create_segmentation`, `create_email_campaign`, `end_discovery_experiment`, `archive_discovery_experiment` |
| **Other requirements** | The `loomi-discovery`, `loomi-engagement` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "Are last month's new arrivals getting seen? Boost the buried ones and email people who'd want them."
- "We launched a new suit range three weeks ago and it isn't selling. Find out why and fix it."
- "Carry on with the new arrivals run: the test should be done." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| find | `new-arrivals-tracker` | now (Discovery) |
| visibility | `discovery-product-visibility` | now, for buried products |
| test | `discovery-experiment-setup` | now, after confirmations |
| audience | `engagement-segment-builder` | now, after its confirmation (Engagement) |
| email | `engagement-email-builder` | now, after its confirmation |
| qa | `campaign-qa` | now, then when the user schedules the send |
| read-out | `discovery-experiment-readout` | after the test has run (`min_test_days`, or the agreed end date) |
| close | `discovery-experiment-close` | after a conclusive read-out |
| measure | `change-impact-tracker` | `measure_after_days` after the close or the send |

The Search side (visibility, test, read-out, close) and the Marketing side (audience, email, qa) can each be skipped on its own: `status` offers the skips with their reasons. `scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records the chosen products as findings, the test and segment writes, the email builder's and the close skill's plan and verify files, and the send the user starts in Engagement, and prints what's next and when. See [examples/buried-suits.md](examples/buried-suits.md).

## Notes and limitations

- One page and one group of products per run (up to `max_chosen`). New products for another page need their own run.
- Slow starts (seen but not bought) and invisible products (no views) are recorded as findings for `product-data-enhancer` and `data-feed-health`, outside the run: a boost or an email won't fix a product page or a feed. The same goes for a buried product whose cause is recall, data or a redirect.
- The email features the products by ID from the Engagement catalog. A new product that isn't in it yet can't be shown: check with `catalog-parity-check`.
- A kept boost has no end date; set one with `discovery-rule-cleanup` so it doesn't hold back the next arrivals.
- The boost and the email overlap in time, so each confounds the other's before-and-after measure. The boost's A/B read-out is the stronger evidence; new products have little "before" data.
