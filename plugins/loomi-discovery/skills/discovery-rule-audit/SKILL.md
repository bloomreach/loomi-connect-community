---
name: discovery-rule-audit
description: Audits Bloomreach Discovery merchandising rules using Loomi Connect and produces a prioritised cleanup list. It covers ranking rules, media rules (banners), facet rules and redirects across site search, category and global scopes, and flags rules that are expired but still on, failing to sync, disabled, never-ending, duplicate or overlapping, attached to queries or categories with no traffic, or stuck in A/B tests. Use when the user asks to audit, review, clean up or tidy merchandising rules, find stale or conflicting rules, or check rule hygiene before a campaign.
license: Apache-2.0
compatibility: Requires the Loomi Connect MCP server (Bloomreach Discovery).
metadata:
  author: bloomreach
  version: "0.2.0"
  products: discovery
  access: read-only
---

# Discovery rule audit

## What this does

Lists every merchandising rule in a Discovery account or site and checks it for problems: expired rules still switched on, rules whose sync failed, old disabled rules, rules with no end date that look temporary, duplicate or conflicting rules for the same query, rules on searches or categories nobody visits, and rules tied to A/B tests, including rules still marked as in a test when no test is running. The result is a cleanup list, ordered by priority, with a suggested action for each rule.

This skill only audits and recommends. It never changes or deletes anything.

## Before you start

This skill uses these Loomi Connect tools:

| Rule type | Site search | Category | Global |
|---|---|---|---|
| Ranking rules | `list_site_search_ranking_rules` | `list_category_ranking_rules` | `list_ranking_rules_global` |
| Media rules (banners, campaigns) | `list_site_search_media_rules` | `list_category_media_rules` | `list_global_media_rules` |
| Facet rules | `list_site_search_facets` | `list_category_facets` | `list_facets_global` |
| Redirects | `search_redirects` | — | — |

Plus: `list_discovery_accounts`, `list_discovery_sites`, `search_discovery_experiments`, `get_discovery_query_performance`, `get_discovery_category_performance_table`, and for detail `get_ranking_rule`, `get_discovery_media_rule` and `get_facet_rule`.

If one of them isn't available, find it with the Loomi Connect `search_tools` tool and run it with `call_tool`. Use read tools only: `search_tools` also returns write tools; never call them.

You need the account, and optionally a site and a rule type. The default traffic window is the last 90 days.

### Rules for calling the tools

- **Make calls one at a time.** Discovery allows 3 requests per second. If a call returns HTTP 429, wait a few seconds and retry.
- **Fetch every page.** Pass `limit=100` to the ranking, media and redirect lists. If `meta.pagination.total` is more than 100, fetch `page=1`, `2` and so on. Facet lists return everything in one call.
- **Large responses.** If the client saves a response to a file, keep the file. `scripts/audit_rules.py` reads the saved files directly.

### Running the scripts

Run each script as one plain command from your own working folder, giving the script's full path: `python3 <this skill's folder>/scripts/audit_rules.py` and its arguments. Pass saved tool results, and any files a script writes (`--out`, `--jsonl`, `--out-dir`), by paths in your working folder, never inside the skill's folder; a bare file name lands in the folder you run from. Don't `cd` into the skill's folder, and don't add `-I`, shell variables, `;`, redirects (`>`), `$(...)` or line breaks: some apps only allow plain commands, refuse the rest and keep skill folders read-only, and then the sums have to be done by hand. Piping the output to `jq` or `head` is fine. Some apps run no scripts at all, so the steps still work by hand.

## Steps

### 1. Resolve the account and site

1. Call `list_discovery_accounts`, and ask if the account is ambiguous.
2. Call `list_discovery_sites`. If there are sites, ask which one (or whether to audit each), and pass its `site_group_id` to every call. If there are **no sites**, leave `site_group_id` out to use the account level.

### 2. List the rules

Call all ten list tools from the table, one at a time, with `limit=100`. Each returns rules with `id`, `name`, `ruleType` (`ranking`, `campaign` for media, `facet`, `redirect`), `enabled`, `syncStatus`, `durationTag` (`unscheduled`, `scheduled`, `active`, `expiringSoon`, `expired`), `startedAt` and `endedAt` (Unix ms), `lastModifiedAt`, `lastModifiedBy`, `queries` (each with `query` and `queryType`), `isAbTestLive` and `variantCount`.

Save each response, or the `data` list, to a file.

Things to know about these lists:

- **Use `durationTag` to find expired rules**, not `syncStatus`. Some expired rules show `syncStatus: "EXPIRED"`, but others still show `"SUCCESS"`.
- `syncStatus: null` means the rule was saved but never synced: usually an abandoned draft.
- Any other `syncStatus` than `SUCCESS` or `EXPIRED` (for example `FAILED`) means the last sync failed, so what shoppers see may not match the rule.
- **`audienceName` in the lists isn't reliable.** It can be null for a rule that does target an audience. Check audiences with `get_ranking_rule` (or `get_discovery_media_rule` or `get_facet_rule`) before you call two rules duplicates.
- **Match type isn't in the lists.** `get_ranking_rule` shows `matchType` (`EXACT_MATCH` or `PHRASE_MATCH`) for each query.
- Facet lists have no `durationTag`. Category rules use category IDs (for example "80200"), not names.

### 3. Get traffic and experiments

1. Call `get_discovery_query_performance` with `days=90`, `page_size=1000` and `sort="visits"`. Check that `total_rows` is no more than the rows returned, and fetch more pages if it is. A rule's query that **isn't in this table** had no tracked searches in the period.
2. Call `get_discovery_category_performance_table` with `days=90` and `page_size=500`. Rows have `cat_id` (the ID that category rules use) and `category` (the name).
3. Call `search_discovery_experiments` with `limit=100` (all statuses). Each bucket's `ruleIdentifierInfo.id` links an experiment to a rule. Don't skip it: without it, a rule marked `isAbTestLive: true` can't be checked against the tests that are really running.

Save each response.

### 4. Run the checks

Run:

```
python3 <this skill's folder>/scripts/audit_rules.py --rules <file> [--rules <file> ...] --queries <query file> --categories <category file> --experiments <experiments file> --today <YYYY-MM-DD>
```

It prints a summary and a cleanup table. If you leave out `--experiments`, the summary says the stuck A/B test check didn't run; say so in your output. If you can't run scripts, apply the checks in [references/audit-checks.md](references/audit-checks.md) by hand.

### 5. Confirm the important findings

The script flags candidates. Confirm the ones that matter before you recommend action. Make these calls one at a time, and limit them to about 15:

- **Duplicates and overlaps.** For each query with more than one enabled rule of the same type, call `get_ranking_rule` (or `get_discovery_media_rule`) on each. Compare `audiences` and `customizationItems`:
  - different audiences → personalisation, which is fine. Note it, but don't flag it;
  - same audience, or none → a real conflict. Note which products or attributes they disagree on, such as one rule boosting a product that another buries.
- **No-traffic rules.** Check `matchType`. A `PHRASE_MATCH` rule for "backpack" still fires for "berry backpack", so check the longer queries with `get_discovery_query_performance` and `search=<query>`. Often the rule targets the wrong wording, for example "backpack" when shoppers type "backpacks". Recommend retargeting rather than deleting.
- **Redirects.** Redirected searches never reach a results page, so they don't appear in query performance. Don't call them "no traffic". Instead, check each destination with `search_redirects` and `rule_id`, and flag destinations that look wrong or out of date. For a full redirect review, use `discovery-redirect-audit`.
- **Global rules.** Several enabled rules on `*` for the same query type must each target an audience (only one un-targeted global rule is allowed). Confirm with `get_ranking_rule`.
- **Experiments.** For a DRAFT experiment, call `get_ranking_rule` on its bucket rules. A 404 means the rule was deleted and the draft can't be started. For a COMPLETED test, check that the losing variant's rule is disabled.

### 6. Write the cleanup list

Group the findings into **Fix now**, **Clean up** and **Review**, using the priorities in [references/audit-checks.md](references/audit-checks.md). For every row, give the rule ID, name, type, query or category, the issue, the evidence and one suggested action.

- Rules named "do not delete" or similar are **protected**. List them, but recommend asking the owner (`lastModifiedBy`) instead of deleting.
- Rules in a running test (`isAbTestLive: true`) can't be changed until the test ends. Say so. If no experiment is RUNNING, the flag is stuck: say that, and still report the rule's other findings.
- Prefer **disable** over **delete** when unsure. Disabling can be undone; deleting can't.

## Output

```
## Discovery rule audit: <account/site> (<date>; traffic: last 90 days)

**Summary:** <n> rules (<n> enabled): ranking <n>, media <n>, facet <n>, redirect <n>. <n> need action now, <n> can be cleaned up, <n> to review.

### Fix now
| Rule | Type | Query / category | Issue | Evidence | Action |
|---|---|---|---|---|---|
| ... |

### Clean up
| ... |

### Review
| ... |

**Protected rules (ask the owner):** <ids and names>
**A/B tests:** <running tests and what they block; drafts that can't start>
**Healthy:** <short note on what looked fine, e.g. redirects, facets>
```

## Safety

This skill is **read-only**. It never creates, changes, disables or deletes rules, redirects, facets or experiments.

If the user asks to apply the cleanup, hand it off. This skill never uses a write tool, even if asked.

1. Give the exact changes for them to make in the Bloomreach Discovery dashboard: which rules change, and how (disable, delete or reschedule), one rule per line. Prefer disabling to deleting.
2. Warn them that **Discovery changes go live immediately**, and that deletes can't be undone.
3. Check for running A/B tests. Rules in a running test can't be changed or deleted.
