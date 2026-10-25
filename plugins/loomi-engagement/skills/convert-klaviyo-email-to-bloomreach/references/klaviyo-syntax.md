# Klaviyo → Bloomreach reference

Status column: **tested** = seen in a real Klaviyo export and validated by build + render-check against a
real Bloomreach sandbox project (Oct 2026). **handled** = implemented from Klaviyo's documented
syntax but not yet seen in a real export — verify the first time you meet it and promote it to tested.
**manual** = not auto-translated; the build reports it as an error or warning.

## Template tags

Klaviyo uses Django-style templates. Bloomreach uses Jinja. Filters with a colon argument
(`|default:'x'`) must become call syntax (`| default('x')`).

| Klaviyo | Bloomreach | Status |
|---|---|---|
| `{{ person.first_name\|default:'friend' }}` | `{{ customer.first_name \| default('friend') }}` (property name from `get_mapping`) | tested |
| `{{ person.<prop> }}` (last_name, email, phone_number, city, region, country, zip) | `{{ customer.<mapped prop> }}` | handled |
| `{{ person\|lookup:'Custom Prop' }}` | `{{ customer.<mapped> }}` or `{{ customer['Mapped Prop'] }}` | handled |
| `{{ first_name }}` (shorthand, older templates) | `{{ customer.first_name }}` | handled |
| `{% if person.x == 'y' %}…{% endif %}` | same, with `customer.<mapped>` | handled |
| `\|default:'x'`, `\|lookup:'k'`, `\|floatformat:2`, `\|truncatechars:n`, `\|upper/lower/title` | `\| default('x')`, `['k']`, `\| float \| round(2)`, `\| truncate(n)`, same | handled |
| `{{ organization.name }}` | `{{ project_variables.<ref> }}` or literal | tested |
| `{{ organization.full_address }}` | project variable or literal — **required**; build fails if missing | tested |
| `{{ organization.url }}` | site URL (literal or project variable) | tested |
| `{% unsubscribe %}`, `{% unsubscribe 'text' %}` | `<a href="{{ consent.page }}">Unsubscribe</a>` (or `email.unsubscribe` on legacy projects) | tested |
| `{% unsubscribe_url %}` | `{{ consent.page }}` | handled |
| `{% manage_preferences %}` | link to `{{ consent.page }}` | handled |
| `{% web_view %}`, `{% web_view_url %}` | `{{ email.view }}` | handled |
| `{% coupon_code 'Name' %}` | `{{ vouchers['<pool>'].assign_available() }}` | handled — needs `mapping.voucher_pools` |
| `{% for item in event.item_ids %}{% catalog item %}…{% endcatalog %}{% endfor %}` | `{% for product in aggregates['<latest cart aggregate>'] %}{% set item = catalogs.<catalog>.item_by_id(product.<id field>) %}{% if item %}…{% endif %}{% endfor %}` — falls back to `event.<list>` (one-item snapshots, see below) | tested |
| `catalog_item.title`, `.url`, `.featured_image.thumbnail.src`, `.featured_image.full.src`, `.metadata\|lookup:"$price"` | `item.title`, `item.url`, `item.image`, `item.image`, `item.price` (renamed via `mapping.catalog_fields`) | tested (title, thumbnail, price) |
| `{% currency_format x %}` | `$<x formatted to 2 decimals>` (symbol from `mapping.currency_symbol`) | tested |
| `{% for item in event.extra.line_items %}` with `item.product.*` | loop is re-pointed to `event.<list>`, **item fields need manual mapping** | manual |
| `{{ event.<prop> }}`, `{{ event\|lookup:'$value' }}` | kept; warning asks to confirm the property exists on the Bloomreach trigger event | manual |
| `{% include %}`, `{% with %}`, `{% firstof %}` | — | manual (build error) |

Klaviyo `$`-prefixed system properties (`$value`, `$event_id`, `$email`) have no direct Bloomreach equivalent.
Find the matching property on the Bloomreach event via `get_event_schema`.

## Flow emails → event triggers

| Klaviyo flow metric | Typical Bloomreach trigger | Item list |
|---|---|---|
| Added to Cart / Started Checkout | `cart_update` (`action = add`) or `checkout` | `product_list: [{product_id, quantity}]` |
| Viewed Product | `view_item` | single `product_id` |
| Placed Order | `purchase` (`purchase_status = success`) | `product_ids` / `product_list` |

Always confirm against the project's `get_mapping.standard_events` and one real event from
`list_customer_events`. Names differ between projects.

**Cart contents: use an aggregate, not `event.*`.** In Klaviyo, `event.item_ids` is the cart at trigger time.
In Bloomreach, each add-to-cart starts its own scenario run, and `event.product_list` is that single event's
snapshot. Previews pick one event, so they often show a single product. The reliable source is a "last
`cart_update.product_list`" aggregate (`aggregates['<id>']`), which is always the customer's current cart.
Verified on a sandbox project (Oct 2026): event source rendered 1 of 3 items, aggregate rendered all 3. This also matches
the abandoned-cart template in Bloomreach's docs.

## Export structure → BEE

A Klaviyo drag-and-drop export is `div.kl-row` (row) → `div.kl-column` (column, width %) →
`div.component-wrapper` (block). The block type is the inner `td` class:

| Klaviyo block | Detected by | BEE module |
|---|---|---|
| Header link bar | `hlb-wrapper` (logo `td.hlb-logo`, links `td.hlb-subblk`) | image (logo) + text (links) |
| Text | `td.kl-text` | text (or custom HTML if it contains `{% for/if %}`) |
| Image | `td.kl-image` | image |
| Button | `td.kl-button` (label in `a` or `p`, colors on `td[bgcolor]`) | button |
| Divider | `p` with `border-top` | divider |
| Spacer | `div` with only a height | spacer |
| Social | ≥2 small icons (≤64px), no text/button | social |
| Anything else | — | custom HTML + warning |

Klaviyo quirks the converter handles:
- **Desktop/mobile duplicates.** Blocks with `desktop-only` / `mobile-only` classes. The desktop version is kept for all
  screens; differences are reported. `mapping.keep_mobile_variants: true` keeps both (untested in the Visual Builder).
- **Head CSS.** `h1`–`h4` and `p` rules live in `<style>`; BEE drops `<head>`, so they are inlined onto elements.
- **Padding cascade.** Klaviyo writes `padding-bottom:0; … padding:20px 50px` — the later shorthand wins.
- **Quoted font stacks.** `"Poppins", "Helvetica Neue"` — normalised to single quotes so `style=""` attributes survive.
- **Outer spacing.** `.root-container-spacing` top/bottom padding becomes spacer rows (BEE has no outer padding).
- **Headings.** A text block that is a single `<h1>`–`<h6>` becomes a BEE heading module. In text modules, TinyMCE
  wraps headings in `<p>` and adds blank lines above and below.
- **Fonts on spans.** Klaviyo often sets the font on an inner `<span>`. The Visual Builder strips unknown fonts from
  spans, so a span that wraps a whole heading/paragraph has its typography moved onto the block element.
- **Web fonts.** Google fonts used in the email (Poppins, Montserrat, …) are registered in the template's
  `webFonts` and linked in `jinja_html`, so the editor keeps them.
- **Loose `<div>`s.** Top-level `<div>` text in a block becomes `<p>` (TinyMCE would wrap it and add blank lines).
- **Dropped automatically.** "Powered by Klaviyo" badge, `TRACKING_PIXEL_TOP/BOTTOM` placeholders, the
  `static-forms.klaviyo.com` font import.
- **Unfinished templates.** Empty `src`, `href=""`, `<p>` buttons with no link, lorem ipsum, HEADLINE / ADD YOUR CTA
  placeholders are reported, not filled in.
- **Images.** Hosted on `d3k81ch9hvuctc.cloudfront.net` or `*.klaviyo*` — rehost with `import_media_file`.
- **Custom fonts.** Klaviyo-hosted custom fonts can't be reused. The font stack is kept, and the web font
  must be added in Bloomreach (or falls back to the next font in the stack).
