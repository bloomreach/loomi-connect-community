# Example: dependency map (illustrative)

**This example is illustrative.** The method and response shapes come from read-only live calls and synthetic tests, but the project, every name and every number are invented. Nothing was changed.

**Prompt:** "Before we delete these, tell me what uses them: the 'Total spend 365d' aggregate, the 'Legacy expression', the 'Old filter' customer filter, the 'newsletter' consent category and the 'unused_var' project variable."

---

## Dependency map: Example Store (production), 2026-11-03

**Verdict:** 5 targets: 2 are blocked because live flows depend on them, 1 needs a draft scenario dealt with first, and 2 can go now, starting with "Legacy expression".

| Target | Kind | Verdict | Direct | Indirect | Live dependants | Why |
|---|---|---|---|---|---|---|
| Total spend 365d | aggregate | Blocked | 2 | 3 | 1 | Expression "Spend band" → segmentation "High spenders" → active scenario "VIP flow"; also a report and a dashboard |
| newsletter | consent category | Blocked | 1 | 0 | 1 | Active scenario "VIP flow" sends its email step under this category |
| Old filter | customer filter | Check first | 1 | 0 | 0 | Used in a condition of the draft scenario "Draft flow" |
| Legacy expression | expression | No dependants found | 0 | 0 | 0 | Nothing checked references it |
| unused_var | project variable | No dependants found | 0 | 0 | 0 | Not used in the 14 scenario and campaign designs checked |

### What depends on each target
- **Total spend 365d:** expression "Spend band" (by ID in its variable bindings, and `used_by`); report "Spend by month" (`used_by`); then segmentation "High spenders" → active scenario "VIP flow" (segmentation fork) and a dashboard.
- **newsletter:** active scenario "VIP flow", email step's consent category.
- **Old filter:** draft scenario "Draft flow", condition step.

### Safe deletion order
1. Legacy expression, unused_var
- **Review first:** Old filter: remove it from "Draft flow" (or delete the draft) first.
- **Blocked:** Total spend 365d: "VIP flow" depends on it through "High spenders". Change the segmentation or stop the scenario first. newsletter: never delete a consent category a live flow sends under.

**What was checked:** 46 segmentations, 58 aggregates, 21 expressions, 12 customer filters (5 fetched), 118 scenarios (14 fetched, with designs), 74 email campaigns (6 fetched, with designs), 9 weblayers (all fetched); SMS campaigns not checked (no access, HTTP 403); reports, funnels and dashboards through `used_by` only.
**How to act:** delete or archive in the Engagement UI, in this order, and check each item's "used by" panel there first.
