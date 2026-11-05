# Playbook: search demand to revenue

Takes one site-search signal and makes it pay twice: it fixes the site so the search finds products, and it tells the people who searched. Seven existing skills run in order: find a rising or failing search, work out why it fails, fix it with a synonym or define a landing collection, size the searchers and draft an email or SMS, read the campaign's results after the send, and check whether the change moved revenue. A hand-off file in your working folder carries the findings, the changes and the dates between stages, so you can pick up after the send.

| | |
|---|---|
| **Products** | Discovery and Engagement (Engagement optional: without it, no campaign) |
| **Access** | **Writes**, through its stage skills only: `discovery-synonym-fixer` creates a synonym switched off and switches it on (live for every shopper after the next sync); `search-demand-to-campaign` creates one email or SMS campaign draft, which sends nothing until a person activates it. Each write only after its own explicit "yes" |
| **Loomi Connect tools** | Those of its stage skills. Writes: `create_synonym`, `update_synonym`, `create_email_campaign`, `create_sms_campaign` |
| **Other requirements** | The `loomi-discovery`, `loomi-engagement` and `loomi-platform` plugins. Python 3 for `scripts/handoff.py` (standard library only); the hand-off file can also be kept by hand |
| **Tested with** | Claude Code: definitions and script tests. Not yet run end to end |
| **Maintainer** | @bloomreach |

## Example prompts

- "What are people searching for that we're not selling? Fix it and email the people who searched."
- "'capris' returns nothing and it's growing. Fix the search and run a campaign on it."
- "Carry on with the search demand run: the email went out last Tuesday." (with its hand-off file)

## How it works

| Stage | Skill | When |
|---|---|---|
| find | `discovery-trending-searches` | now |
| triage | `discovery-zero-results-triage` | now, for a failing search |
| fix | `discovery-synonym-fixer` | now, after confirmations, for a synonym fix |
| collection | `topic-collection-builder` | now, when no good landing page exists |
| campaign | `search-demand-to-campaign` | now, after its confirmation |
| digest | `engagement-campaign-digest` | `digest_after_days` after the campaign, or after the send date |
| measure | `change-impact-tracker` | `measure_after_days` after the fix, or after the send |

`scripts/handoff.py` keeps the hand-off file (the format is in [docs/hand-off-format.md](../../../../docs/hand-off-format.md)): it records the chosen search as a finding, reads the synonym fixer's plan and verify files into the change log, records the draft, and prints what's next and when. See [examples/capris-gap.md](examples/capris-gap.md).

## Notes and limitations

- One search per run. Stages a search doesn't need are skipped (a triage for a search that already sells, a synonym for a catalog gap). Without an Engagement project, the run stops after the site fix and its measurement.
- A redirect candidate is handed to `discovery-redirect-fixer` outside the run; this playbook doesn't run it.
- `topic-collection-builder` only defines the collection: no Loomi Connect tool creates a Discovery dynamic category, so the user sets it up in the dashboard.
- Without a search event in Engagement (tracking tier D), the campaign stage gives a brief and the tracking to add, but no draft, and the digest is skipped.
- There's no A/B test in Engagement here: the measure stage is a before-and-after estimate against the site-wide trend (`change-impact-tracker`).
