# Example: migrating a Mailchimp and an SFMC email

Illustrative output. The brand, project, URLs and IDs are invented.

**Prompt:** "We're moving this client to Bloomreach. Migrate their Mailchimp newsletter and the welcome email from Marketing Cloud." (two HTML exports attached)

---

## What the analysis found

| Email | Source | Layout | Tokens |
|---|---|---|---|
| Autumn newsletter | Mailchimp | 4 rows: header, text + button, 2-column products, footer with social icons | 13, all translated automatically; `*\|TIER\|*` needs a project field |
| Welcome | Salesforce Marketing Cloud | 2 rows: logo, text + button, dark footer | 15; 5 AMPscript tokens need a translation |

## Mapping (confirmed once per client)

| Source | Bloomreach | How |
|---|---|---|
| `*\|FNAME\|*`, `%%=v(@firstName)=%%` | `{{ customer.first_name \| default('there', true) }}` | auto / translated (AMPscript set `@firstName` with a "there" fallback) |
| `*\|TIER\|*`, `@tier` | `customer.loyalty_tier` | `get_customer_property_schema` (used) |
| `%%[ SET @firstName … ]%%` (setup block) | `""` | its logic moved into the tokens above |
| `%%[ IF @tier == "Gold" THEN ]%%` … `%%[ ELSE ]%%` … `%%[ ENDIF ]%%` | `{% if customer.loyalty_tier == 'Gold' %}` … `{% else %}` … `{% endif %}` | translated |
| `*\|UNSUB\|*`, `%%unsub_center_url%%`, `%%profile_center_url%%` | `{{ consent.page }}` | consent framework enabled |
| `*\|LIST:COMPANY\|*`, `%%Member_Busname%%` | `{{ project_variables.company_name }}` | project variable |
| `*\|HTML:LIST_ADDRESS_HTML\|*`, `%%Member_Addr%%` | `{{ project_variables.address }}` | project variable (city/state parts dropped) |
| `*\|FACEBOOK:PROFILEURL\|*` | `https://www.facebook.com/examplebrand` | given by the user |

## Write plan (approved before anything was written)

```
Project: Example Brand Sandbox (example-brand-sandbox)
Will upload 5 images to the media library:
  - autumn-newsletter-1 … autumn-newsletter-3  ← mcusercontent.com/…/images/…
  - welcome-1, welcome-2  ← image.s10.sfmc-content.com/lib/…
Will create 2 draft scenarios (nothing is activated or sent):
  - [Migrated – Mailchimp] Autumn newsletter   trigger: now
  - [Migrated – SFMC] Welcome                  trigger: event registration
Nothing else will change.
OK to go ahead?
```

User: "Yes."

## Migration report

| Email | Scenario | Converted | Needs attention before activating |
|---|---|---|---|
| Autumn newsletter | [Migrated – Mailchimp] Autumn newsletter | Layout (2-column product row, button, social icons), 3 images rehosted, greeting condition, loyalty tier, footer | Static code `AUTUMN20` kept as text: switch to a voucher pool? The Twitter icon had no profile URL, so it links to `#`. Subject drafted (not in the export) |
| Welcome | [Migrated – SFMC] Welcome | Layout, 2 images rehosted, Gold-member condition, footer | The "Shop the sale" link still carries `utm_source=sfmc`. Add a wait node if the welcome shouldn't send instantly |

Both emails were verified after the push (Visual Builder design present). Open each once in the Visual Builder and save it.

Optional next steps you can ask for: swap the static product row for a recommendations model, or replace `AUTUMN20` with a voucher pool.
