# Example: migrating two Klaviyo emails

Illustrative output. The brand, project, URLs and IDs are invented.

**Prompt:** "Migrate these two Klaviyo emails into our Bloomreach project." (two HTML exports attached)

---

## Mapping (confirmed once per client)

| Klaviyo field | Bloomreach field | Source |
|---|---|---|
| `person.first_name` | `customer.first_name` | `get_mapping` |
| `person.email` | `customer.email` | `get_mapping` |
| `person\|lookup:'Loyalty Tier'` | `customer.loyalty_tier` | `get_customer_property_schema` (used) |
| `organization.name` | `{{ project_variables.company_name }}` | project variable |
| `organization.full_address` | `{{ project_variables.address }}` | project variable |
| `{% unsubscribe %}` | `{{ consent.page }}` | consent framework enabled |
| `event.extra.line_items` loop | `aggregates['<latest cart aggregate>']` + `catalogs.products.item_by_id()` | aggregate "Latest cart products" |
| Coupon `WELCOME10` | voucher pool "Welcome 10%" | `search_voucher_pools` (available: 4,812) |

## Write plan (approved before anything was written)

```
Project: Example Brand Sandbox (example-brand-sandbox)
Will upload 7 images to the media library:
  - welcome-1 … welcome-4  ← d3k81ch9hvuctc.cloudfront.net/company/XXXX/images/…
  - abandoned-cart-1 … abandoned-cart-3  ← d3k81ch9hvuctc.cloudfront.net/company/XXXX/images/…
Will create 2 draft scenarios (nothing is activated or sent):
  - [Migrated – Klaviyo] Welcome #1         trigger: now
  - [Migrated – Klaviyo] Abandoned cart #1  trigger: event cart_update (action = add)
OK to go ahead?
```

User: "Yes."

## Migration report

| Email | Scenario | Converted | Needs attention before activating |
|---|---|---|---|
| Welcome #1 | [Migrated – Klaviyo] Welcome #1 | Layout, 4 images rehosted, first name with fallback, coupon → voucher pool, unsubscribe, address | Subject and preview text were drafted (not in the export); confirm them. Footer "Instagram" icon links to `#` |
| Abandoned cart #1 | [Migrated – Klaviyo] Abandoned cart #1 | Layout, 3 images rehosted, cart loop from the latest-cart aggregate (render check showed all 3 items) | Add a wait node and a "didn't purchase" condition before the email. The mobile-only "Free returns" banner was dropped (desktop version kept) |

Both emails were verified after the push (Visual Builder design present, HTML about 12 KB each). Open each once in the Visual Builder and save it.

Optional next steps you can ask for: swap the static "You might also like" block for a recommendations model, or add a second reminder email.
