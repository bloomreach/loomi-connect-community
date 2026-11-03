# Closing a Discovery experiment: what each write does

This skill is the other half of `discovery-experiment-setup`. The write behaviour below comes from the Loomi Connect tool descriptions and the published `discovery-experiments` guide. The skill's authors haven't run these writes; the read-back after each step is how the skill confirms what really happened.

## The end of the state machine

```
RUNNING ── end_discovery_experiment ──▶ COMPLETED ── archive_discovery_experiment ──▶ ARCHIVED
           LIVE at once, can't be undone              no live impact; no Loomi Connect tool unarchives
```

- Only a RUNNING test can be ended, and only a COMPLETED test can be archived. A DRAFT never ran: edit or delete it in the Discovery dashboard.
- Experiments are scoped to an environment (`production` or `staging`). Pass the experiment's `environment_used` to every call, and check `environment_used` in each response. The script never assumes an environment. Leave out `site_group_id` when the account has no sites.

## What "keep a bucket" means

Each bucket either applies a rule (`ruleIdentifierInfo` holds its ID) or is **default behaviour** (`ruleIdentifierInfo: null`). The control can be either: in Pattern 1 the control is default behaviour, in Pattern 2 it's today's rule, and some tests put the rule in the control and default behaviour in the test bucket.

| Bucket to keep | Ending call | What happens (from the tool description) |
|---|---|---|
| A bucket with a rule | `end_discovery_experiment` with `winner_bucket_id` = that bucket's `id` | That rule serves 100% of traffic for the test's scope at once; every other bucket's rule is disabled |
| Default behaviour | `end_discovery_experiment` with **no** `winner_bucket_id` | Every bucket's rule is disabled; traffic returns to default. No winner is recorded |

**Seen on a demo account:** two COMPLETED tests whose winner was the default-behaviour bucket left their losing rule at `enabled: false`, `isLive: false`.

**Unverified:** that a winning rule is left `enabled: true` after ending (no completed test with a winning rule was available), and how ending treats a rule in the losing bucket of a Pattern 2 test. So after ending, read every bucket's rule back with `get_ranking_rule`:

- the kept rule should be `enabled: true` with `syncStatus: SUCCESS`; if it isn't, `update_ranking_rule` with `enabled: true` turns it on (its own "yes");
- every other bucket's rule should be `enabled: false`; if one isn't, `update_ranking_rule` with `enabled: false` turns it off (its own "yes"). Two enabled rules on the same query fight each other.

There's no separate "promote" step: once the test has ended, the kept rule is an ordinary rule. It keeps its test name (often starting "TEST"); renaming it is a dashboard change this skill doesn't make.

## Payloads

```json
{"account_name": "<account>", "environment": "production", "site_group_id": "<site>", "experiment_id": 12345, "winner_bucket_id": 678}
```

`end_discovery_experiment`. Leave out `winner_bucket_id` to keep default behaviour.

```json
{"account_name": "<account>", "environment": "production", "site_group_id": "<site>", "rule_id": 2234567, "enabled": false}
```

`update_ranking_rule`. Only the fields you pass change. Undo: the same call with `enabled` flipped.

```json
{"account_name": "<account>", "environment": "production", "site_group_id": "<site>", "experiment_id": 12345}
```

`archive_discovery_experiment`. COMPLETED only.

## Rules in other forms

Experiments can also test keyword redirects (`ruleType: "redirect"`). This skill ends and archives those tests, and reads the redirect back with `search_redirects` and `rule_id`. If a redirect needs switching on or off afterwards, it gives the user the change to make in the Discovery dashboard: it has no redirect write tool.
