# Change file format

`scripts/redirect_plan.py --changes <file>` reads a JSON list of the redirect changes to plan. Write it from the user's request, or from a `discovery-redirect-audit` or `discovery-search-category-match` finding. One object per change:

| Field | For | Meaning |
|---|---|---|
| `action` | all | `create`, `update` or `delete` |
| `rule_id` | update, delete | The redirect's ID from `search_redirects` |
| `queries` | create; update (replaces the whole list) | Keywords, as shoppers type them |
| `redirect_type` | create; update | `redirect_terms` (exact match), `redirect_phrases` (phrase match), `do_not_redirect_terms` or `do_not_redirect_phrases` (block other redirects for those keywords) |
| `destination_url` | create; update | A full `https://` URL. Required for `redirect_terms` and `redirect_phrases` |
| `name` | optional | Display name |
| `enabled` | update | `false` switches a redirect off (the safest fix); `true` switches one on |
| `started_at`, `ended_at` | optional | ISO date or time (`2026-12-01`, `2026-12-01T09:00:00Z`), or Unix milliseconds |
| `audience_id` | optional | An audience ID from `list_discovery_audiences` |
| `reason` | optional | Why: the finding it fixes. Shown in the plan |

Example:

```json
[
  {"action": "update", "rule_id": 9001, "destination_url": "https://www.example-shop.test/returns", "reason": "URL had no https://"},
  {"action": "update", "rule_id": 9002, "enabled": false, "reason": "Phrase match 'sale' catches 'sale dresses'"},
  {"action": "create", "queries": ["track order", "order status"], "redirect_type": "redirect_terms",
   "destination_url": "https://www.example-shop.test/orders", "name": "Track order", "reason": "Navigational search with no redirect"},
  {"action": "delete", "rule_id": 9003, "reason": "Duplicate of 9001"}
]
```

New redirects are always planned **disabled** (`enabled: false`), because `create_redirect` makes a rule live by default. Switching it on is a separate step in the plan, with its own "yes".

The plan gives an undo for every change:

| Change | Undo |
|---|---|
| update | `update_redirect` with the fields' values before the change |
| create | `delete_redirect` on the new rule's ID (known only after the create) |
| delete | `create_redirect` from the saved before state. The rule comes back with a new ID and no edit history |

`update_redirect` treats an omitted field as "keep", so a schedule that was added can't be removed by an update. The plan says so, and that undo is done in the Discovery dashboard.
