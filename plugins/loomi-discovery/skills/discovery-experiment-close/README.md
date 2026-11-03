# Discovery experiment close

Closes a finished Bloomreach Discovery A/B test: checks the evidence, ends the test keeping the winning bucket (or today's behaviour), confirms exactly the right ranking rule is left on, and archives it. Each write needs its own confirmation. It's the other half of `discovery-experiment-setup`, and usually follows `discovery-experiment-readout`.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | **Writes**: ends an experiment (live at once, can't be undone), switches a ranking rule on or off when ending left it in the wrong state, and archives the experiment. Each only after an explicit "yes" |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `search_discovery_experiments`, `get_discovery_experiment_report`, `get_ranking_rule`, `search_redirects`; writes: `end_discovery_experiment`, `update_ranking_rule`, `archive_discovery_experiment` |
| **Other requirements** | Python 3 for `scripts/close_plan.py` (standard library only) |
| **Tested with** | Claude Code: script tests and read-only calls on a demo account. The write calls themselves are designed from the tool schemas and haven't been run |
| **Maintainer** | @bloomreach |

## Example prompts

- "The rain jacket test won, ship it"
- "End the 'Search terms - shirt' experiment and keep the current ranking"
- "Close and archive last month's Discovery tests"

## Example output

See [examples/close-brand-boost.md](examples/close-brand-boost.md).

## Notes and limitations

- It refuses to ship a change the evidence doesn't support (confidence under `min_confidence`, a test shorter than `min_days`, a guardrail metric clearly worse, or no report), unless you explicitly override after seeing why. The thresholds are in `references/rules.json` and match `discovery-experiment-readout`.
- It never assumes the environment or the site: every write carries the experiment's environment, and the site when the account has sites.
- Ending a test can't be undone, and a completed test can't be restarted. Loomi Connect has no tool to unarchive an experiment.
- What ending does to each rule comes from the tool descriptions; the skill reads every rule back afterwards and fixes any left in the wrong state, with your confirmation.
- Redirect tests are ended and archived, but a redirect left in the wrong state is a change you make in the Discovery dashboard.
