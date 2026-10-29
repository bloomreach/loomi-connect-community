# Audit checks and priorities

These are the checks `scripts/audit_rules.py` runs, so you can apply them by hand if scripts aren't available.

| Check | How to spot it | Priority | Suggested action |
|---|---|---|---|
| **Sync failed** | `syncStatus` is set and is not `SUCCESS` or `EXPIRED` (for example `FAILED`) | Fix now | Open it in the Dashboard and save it again. If it fails again, raise it with Bloomreach support. What shoppers see may not match the rule |
| **Expired but still switched on** | `enabled: true` and `durationTag: "expired"` (or `endedAt` in the past) | Fix now | Disable it, or delete it if the campaign is over. It no longer serves, but it clutters the list and can be turned back on by mistake if someone edits its dates |
| **Same-audience conflict** | Two or more enabled rules of the same type for the same query, with the same audience (or none) | Fix now, if they disagree on products; otherwise Clean up | Merge them into one rule |
| **Rule on a query or category with no traffic** | Enabled; its sitesearch query isn't in the query performance table, or its category ID isn't in the category table, for the period | Clean up | If a close wording has traffic ("backpacks" vs "backpack"), retarget the rule. Otherwise delete it. Check `matchType` first |
| **Never synced** | `syncStatus: null`, usually with `enabled: false` | Clean up | Delete it, or finish and enable it |
| **Seasonal rule that never ends** | Enabled, `durationTag: "unscheduled"`, and the name mentions a sale, a season, a holiday, a campaign, "demo" or "test" | Clean up | Add an end date, or disable it |
| **Stale disabled rule** | `enabled: false`, last modified 90 or more days ago | Clean up | Delete it if nobody needs it |
| **Expired and disabled** | `enabled: false`, `durationTag: "expired"` | Clean up | Delete it |
| **Several global rules on `*`** | More than one enabled rule with query `*` for the same query type | Review | Only one un-targeted global rule is allowed per type. Confirm the others target audiences |
| **Draft experiment that can't start** | DRAFT experiment whose bucket rule returns 404 from `get_ranking_rule` | Clean up | Delete the draft in the Dashboard |
| **Old draft experiment** | DRAFT experiment, not modified for 90 or more days | Clean up | Delete it, or start it |
| **Trial-run experiment** | COMPLETED, ran for under a day | Review | Archive it so nobody reads it as a real result |
| **Losing variant still on** | COMPLETED experiment; the non-winning bucket's rule is still enabled | Fix now | Disable the losing rule |
| **A/B test flag stuck** | `isAbTestLive: true`, but no experiment in the experiments list is `RUNNING`. Needs the experiments list; without it, say this check didn't run | Clean up | Check the experiment ended properly in the Dashboard. The flag may block changes to the rule. Run the rule's other checks too |
| **In a running test** | `isAbTestLive: true` and an experiment is `RUNNING` | Review (info) | Can't be changed until the test ends. Skip the rule's other checks |
| **Protected name** | Name contains "do not delete", "do not change" or similar | Review (info) | Ask the owner (`lastModifiedBy`) before changing it |

## Notes

- **Never-ending rules are normal.** Most evergreen rules have no end date. Only flag ones whose name suggests they were temporary.
- **Disabled isn't harmless.** Old disabled rules make the Dashboard hard to read, and they're easy to re-enable by mistake. But they don't affect shoppers, so they're lower priority than anything enabled.
- **Media rules** (`ruleType: "campaign"`) show banners. An expired banner that's still enabled is usually harmless to shoppers, but it's a sign of a missed cleanup.
- **Personalised duplicates are fine.** One default rule plus audience-specific rules for the same query is a common, deliberate pattern.
- **Don't judge redirects on query performance.** A redirected search goes straight to another page, so it never appears in the search query table. Review redirects by destination and purpose instead (`search_redirects` with `rule_id` shows the URL).
- **Traffic gaps can be tracking gaps.** If a query you'd expect to be popular shows no traffic, check pixel health before deleting rules.
