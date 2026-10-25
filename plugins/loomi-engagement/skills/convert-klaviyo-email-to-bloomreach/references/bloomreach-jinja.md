# Bloomreach Engagement Jinja — validated syntax

Source page IDs refer to pages in the Bloomreach documentation (for example through the Bloomreach Docs MCP server's `fetch` tool).

| Need | Syntax | Source |
|---|---|---|
| Customer property | `{{ customer.first_name \| default('there') }}`; names with spaces `{{ customer['Loyalty Tier'] }}` | engagement/personalization-using-jinja |
| Trigger event property | `{{ event.total_price }}` or `{{ event['prop'] }}` — only in event-triggered scenarios, empty otherwise | engagement/personalization-using-jinja |
| Catalog lookup | `{% set item = catalogs.<catalog_name>.item_by_id(product.product_id) %}` then `{{ item.title }}` etc. | engagement/email-template-abandoned-cart |
| Cart loop | `{% for product in aggregates['<aggregate id>'] %}…{% endfor %}` with an aggregate = last `cart_update.product_list` (`product.product_id`, `product.quantity`). `event.product_list` only holds the triggering event's snapshot | engagement/email-template-abandoned-cart; verified on real data |
| Recommendations | `{% for item in recommendations('<model_id>', 4) %}` or indexed `recommendations('<id>')[0].image` | engagement/email-template-abandoned-cart |
| Voucher | `{{ vouchers['<pool name>'].assign_available() }}`; `assign_available(cached = false)` for a new code per use | engagement/vouchers |
| Unsubscribe | `{{ consent.page }}` (consent framework on); `{{ email.unsubscribe }}` (legacy) | engagement/personalization-using-jinja, engagement/consent-page |
| View in browser | `{{ email.view }}` | engagement/create-email-campaigns |
| Project variable | `{{ project_variables.<JinjaReferenceName> }}` (plural) | engagement/project-variables |
| Brand name | `{{ brand_name }}` | loomi://guides/email-template-best-practices |
| Price formatting | `{{ '%.2f' \| format(item.price \| float) }}` | standard Jinja |

Notes:
- `{{ voucher('pool') }}` (singular, function form) is **not** valid Bloomreach syntax.
- If a voucher pool runs out, the email is not sent and an `enqueue_failed` campaign event is logged.
- The consent page link only works in live sends, not in test emails.
- The voucher token is not rendered by `render-check`; it substitutes `TEST-…-CODE`.
