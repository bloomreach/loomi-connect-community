# Example: checking a boost rule before it goes live

Synthetic data (the test fixtures in `tests/fixtures/discovery/change_qa/`), with page one cut to 5 products to keep it short.

**Prompt**

> Before I switch on rule 900001 for "dress", can you check it? It's our holiday sale boost for Acme.

**Response**

🟡 GO WITH CAUTION: holiday sale boost for Acme on "dress" · 0 blockers · 8 warnings · 1 nitpick
Touches: 1 search · 9,000 visits · $52,000 revenue in the last 30 days ("dress", exact match)

| # | Severity | Check | Query | Issue | Fix |
|---|---|---|---|---|---|
| 1 | 🟡 Warning | Top sellers | "dress" | 2 top sellers pushed off page one: Floral Midi Dress (#1 by revenue, also buried by this rule) and Black Wrap Dress (#2) | Lower the strength, or pin the top sellers you want to keep |
| 2 | 🟡 Warning | Relevance | "dress" | Boosted product "Leather Belt" doesn't look like a dress | Take it out of the boost |
| 3 | 🟡 Warning | Not in results | "dress" | Pinned product p99 isn't in the results for "dress" | Check the ID, or add it to recall too |
| 4 | 🟡 Warning | Stock | "dress" | Out-of-stock "Acme Sequin Dress" moves onto page one | Leave it out of the boost |
| 5 | 🟡 Warning | Brand mix | "dress" | Acme would hold 80% of page one (0% today) | Lower the boost strength |
| 6 | 🟡 Warning | Schedule | — | A holiday sale rule with no end date stays live after the sale | Set an end date |
| 7 | 🟡 Warning | Conflict | "dress" | Enabled ranking rule 800001 already targets "dress" | Check it with get_ranking_rule; edit one rule instead of stacking two |
| 8 | 🟡 Warning | Conflict | "dress" | Enabled ranking rule 800004 is scheduled on "dress" later and would stack | As above |
| 9 | ⚪ Nitpick | Strength | — | Brand boost at strength 90 behaves like a hard sort | Start at 30–50 |

**Before and after: "dress"** (strongest case, simulated)

| New | Was | Brand | Title | Why |
|---|---|---|---|---|
| 1 | 7 | Acme | Leather Belt | boosted |
| 2 | — | ? | (product p99, not in the results) | pinned to slot 2 |
| 3 | 9 | Acme | Acme Sequin Dress | boosted |
| 4 | 6 | Acme | Acme Party Dress | brand boosted |
| 5 | 8 | Acme | Acme Maxi Dress | brand boosted |

Brand mix on page one: before Northwind 2, Contoso 2, Fabrikam 1; after Acme 4, unknown 1.

**Not checked**: nothing.

**Next step**: drop the belt and the out-of-stock dress from the boost, fix or remove the p99 pin, set an end date, bring the strength down to about 40, and check how this rule and rule 800001 interact. Then run this check again. To measure the effect rather than switch it on for everyone, use discovery-experiment-setup.
