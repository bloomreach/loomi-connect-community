# Change file format

`scripts/catalog_fix_plan.py plan --changes <file>` reads a JSON list of the catalog item changes the user asked for. Use it for changes that don't come from a `catalog-parity-check` finding, or to give a value the parity output can't (a stock quantity, a full title, a sale price to clear). One object per change:

| Field | For | Meaning |
|---|---|---|
| `action` | all | `update` or `delete` |
| `item_id` | all | The Engagement item ID (`_id` from `get_catalog_item`) |
| `set` | update | The properties to change and their new values, for example `{"price": 45, "stock_level": 0}`. Only these change; every other property is sent back exactly as read |
| `user_asked` | delete | Must be `true`: a delete is planned only when the user asked to delete this item by name or ID |
| `reason` | optional | Why: the finding or request it comes from. Shown in the plan |

Example:

```json
[
  {"action": "update", "item_id": "P200", "set": {"price": "45.00", "stock_level": 0}, "reason": "Price cut and sold out on the site"},
  {"action": "delete", "item_id": "OLD1", "user_asked": true, "reason": "Discontinued; the user asked to remove it"}
]
```

What the plan does with each change:

| Situation | Result |
|---|---|
| A field that matches `protected_field_pattern` (margin, cost and similar) | blocked: never changed |
| A field the catalog doesn't define | blocked: writing it would add a field to the catalog's schema |
| A number field given text that isn't a number | blocked |
| The item isn't in the catalog | blocked for an update (`upsert_catalog_item` would create it); `no_change` for a delete |
| The item wasn't read | blocked: read it with `get_catalog_item` first |
| The item already has these values | `no_change` |
| A delete without `"user_asked": true` | blocked |
| An update and a delete for one item | blocked: plan one or the other |

Number fields keep the catalog's type: a field the catalog defines as a number gets a JSON number, and a text field that holds numbers gets text (`"45.00"` stays text). Stock words from a parity finding follow the item's own vocabulary (`stock_text_pairs` in [rules.json](rules.json)): "low stock" or "preorder" become "out of stock", "FALSE" becomes "TRUE". A stock word in no pair, such as "discontinued", blocks the fix: give the value in a change file. A numeric stock field goes to `stock_out_number` when out of stock; marking it in stock needs a quantity from the user.

The undo for every change is `upsert_catalog_item` with the full item as it was read, so it restores the item exactly, protected fields included. For a delete, the undo recreates the item.

If the user changes their mind about a value, edit this file and build the plan again: only changes in the saved plan are written.
