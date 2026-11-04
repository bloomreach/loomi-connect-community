# Engagement revenue change explainer

Explains a change in revenue, orders or AOV from **Engagement purchase events**, through **buyers, new vs returning**, orders per buyer and order value. For a Discovery site, use `revenue-anomaly-explainer`.

- **Checks the data first:** history depth, missing days, data that stops before the period ends, one purchase event per order status, repeated order IDs and mixed currencies. A failed check is reported before any explanation, because it changes the answer.
- **Splits the change with maths that multiplies back:** revenue ratio = buyers ratio × orders-per-buyer ratio × average order value ratio, plus a money split that adds up to the cent. A bundled script does the sums; the steps also work by hand.
- **Breaks the biggest driver down:** retained, reactivated and new buyers; campaign attribution and source; country, store or currency; buyers by number of orders; category when the item-level data covers both periods. Each segment comes with its share of the change, and the daily shape shows whether the change started on one date.

It never changes anything.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `get_project_overview`, `get_event_schema`, `get_customer_property_schema`, `estimate_eql_cost`, `execute_analytics_eql`, optionally `search_catalogs` and `search_catalog_items` (all listed directly; if a client doesn't show one, the skill finds it with `search_tools` and runs it with `call_tool`) |
| **Other requirements** | None. Python 3 is optional, for the bundled script |
| **Tested with** | Claude Code, November 2026, read-only against a sandbox project: one month compared with the previous one, every pattern in [references/eql-patterns.md](references/eql-patterns.md) run live (16 queries, 5 cost estimates), with the totals cross-checked three ways (status totals, retained + reactivated + new, buyers by order count). The catalog mapping for category wasn't run, because the item-level event didn't cover the test periods. `scripts/revenue_split.py` tested on synthetic fixtures (`tests/engagement/test_engagement_revenue_change_explainer_revenue_split.py`), including the worked example in [references/decomposition.md](references/decomposition.md). Not tested in an OpenAI client |
| **Maintainer** | @pavelsafarikbr |

## Example prompts

- "Why did revenue double in July compared with June?"
- "Orders are down 15% week on week. What happened?"
- "AOV dropped this month. Is it price or mix?"
- "Compare revenue this October with last October and explain the difference."

See [examples/month-over-month.md](examples/month-over-month.md) for an anonymised answer from the test run.

## How it differs from revenue-anomaly-explainer

[revenue-anomaly-explainer](../../../loomi-platform/skills/revenue-anomaly-explainer/) works on a **Discovery** site. It reads the Discovery dashboards (visits × conversion × order value, search vs category pages, devices, queries and products) and checks merchandising rules, A/B tests, the tracking pixel and catalog feeds.

This skill works on **Engagement** purchase events, at customer level. It explains a change through **who bought** (buyers × orders per buyer × order value, then retained, reactivated and new buyers) and through what the purchase events carry (campaign attribution, source, country, store), using EQL. Use it when the question is about Engagement revenue or CRM-driven sales, or when the project has no Discovery site.

## Scripts

- `scripts/revenue_split.py` (Python 3 standard library, no network): reads the saved EQL results for both periods and returns revenue, orders, buyers, orders per buyer and AOV, the ratios and the check that they multiply back, the main driver, the log-mean money split, revenue per day, retained / reactivated / new buyers, each breakdown segment's share of the change, and duplicate-order counts (never the IDs). Thresholds are in [references/rules.json](references/rules.json).

## Notes and limitations

- EQL is limited to about one query every 3 seconds across the whole Engagement instance, shared with other users. The skill waits about 5 seconds between queries and, on "Too many requests" (HTTP 429), waits for `Retry-After`. A full run takes a few minutes.
- Revenue sums are rated "high" by `estimate_eql_cost`, even on small projects. The skill says how many queries it will run and asks once before running them; it never runs "very high" ones.
- EQL has no distinct count of a property, so orders are counted as completed purchase events after checking that order IDs don't repeat. If they do, the skill reports the surplus rather than guessing.
- "New" buyers depend on how far back the project's purchase history goes. The skill checks the oldest event first and says when the split isn't reliable.
- Unique buyers don't add up across rows of an event breakdown (a customer can buy through two sources); revenue and orders do. The skill only adds up what adds up.
- Category splits need the item-level event to cover both periods. Mapping order product IDs to the catalog is offered but slow, and partial when IDs are missing from the catalog.
- Causes are matched by timing and size; confidence is judgement, not statistics.
