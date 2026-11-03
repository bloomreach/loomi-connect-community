# Discovery API health

Checks whether Bloomreach Discovery's APIs are healthy and whether usage is within contract, and returns one red, amber and green summary with dates:

- **Volume** by request type (keyword search, category, autosuggest, bestseller and other): drops, surges and request types that stopped, against the same weekday over the previous four weeks;
- **Errors:** 4xx and 5xx share of all requests, against fixed limits and their own baseline;
- **Staging:** production traffic moving to the staging environment;
- **Sites and regions** (optional): ones that went quiet;
- **Contract:** monthly unique visitors against the contracted limit, with a forecast for the current month.

It reads usage counts only, and never changes anything.

| | |
|---|---|
| **Products** | Discovery |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_discovery_accounts`, `list_discovery_sites`, `get_discovery_api_requests`, `get_discovery_unique_visitors` |
| **Other requirements** | Python 3 for `scripts/api_health.py` (standard library only); the steps also work by hand |
| **Tested with** | Claude Code (read-only calls on a Bloomreach demo account to check response shapes and filters; the script against synthetic data) |
| **Maintainer** | @bloomreach |

## Example prompts

- "Is search down? Category pages look empty."
- "Did our Discovery API errors spike this week?"
- "Are we within our MUV contract this month?"
- "Why did autosuggest requests drop on Tuesday?"

See [examples/example-api-health.md](examples/example-api-health.md) for an example report.

## Notes and limitations

- `get_discovery_api_requests` gives one total per filter and applies **one filter per call**: combined filters silently mislead. The skill makes about eight small calls, one at a time.
- Request types can't be listed, and an unknown type returns zeros. The skill checks the types in `references/rules.json` and reports the rest as "other".
- A month's unique visitor figure appears on the 2nd of the following month, so the current month is forecast from recent complete months. Accounts not on MUV-based pricing have no contracted limit.
- Thresholds are in `references/rules.json`; adjust them to your own service levels.
