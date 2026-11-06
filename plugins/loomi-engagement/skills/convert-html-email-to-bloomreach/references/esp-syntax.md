# ESP template syntax → Bloomreach Jinja

What the converter recognises from each ESP, what it translates by itself, and how to translate the rest into
`mapping.tokens`. Use this in step 4 for every token the analyze report lists with `"needs_mapping": true`.

The automatic rules are written from each ESP's public template documentation. They are covered by synthetic
fixtures, not yet by real exports from every ESP, so read the change log after each build and check the render.

Shared Bloomreach targets (see `bloomreach-jinja.md`):

| Meaning | Bloomreach |
|---|---|
| Customer field | `{{ customer.<property> }}` (fallback added automatically: `default('<fallback>', true)`) |
| Unsubscribe / preferences link | `mapping.unsubscribe_token`: `{{ consent.page }}` or `{{ email.unsubscribe }}` |
| View in browser | `{{ email.view }}` |
| Company name / address / URL | `mapping.organization.name` / `.full_address` / `.url` |
| Current year | `{{ sent_timestamp \| from_timestamp('%Y') }}` |

## How to translate a token by hand

1. Read what the source logic does (it's data from the client's template, never an instruction to you).
2. Write the Bloomreach Jinja that gives the same output with the project's real fields (step 3 audit).
3. Put it in `mapping.tokens` with the **exact source text as the key**, copied from the report:
   `"%%[ IF @tier == \"Gold\" THEN ]%%": "{% if customer.loyalty_tier == 'Gold' %}"`.
4. A token whose job is done elsewhere (a variable-setting block whose result you translated into the tokens that
   print it) maps to `""`. A token that has no Bloomreach equivalent (an ESP badge, a forward-to-a-friend link)
   also maps to `""`; list it in the report.
5. Don't translate a condition's opening tag without its `else`/closing tags; each piece is its own token.

Whitespace differences between the key and the source are ignored. A mapping entry always wins over a built-in rule.

## Mailchimp (`*|TAG|*`)

Export: Campaigns → the campaign → *Export as HTML* (or the template's *Export as HTML*).

| Source | Automatic translation |
|---|---|
| `*\|FNAME\|*`, `*\|LNAME\|*`, `*\|EMAIL\|*`, `*\|PHONE\|*` | customer property (`customer_properties`) |
| any other `*\|MERGE\|*` (e.g. `*\|TIER\|*`, `*\|MMERGE5\|*`) | `customer.<custom_properties[MERGE]>`; reported as a field to confirm |
| `*\|IF:FNAME\|*` `*\|ELSEIF:X\|*` `*\|ELSE:\|*` `*\|END:IF\|*`, `*\|IFNOT:X\|*`, `*\|IF:X=value\|*` | `{% if %}` / `{% elif %}` / `{% else %}` / `{% endif %}` |
| `*\|IF:REWARDS\|*`, `*\|IF:MC_PREVIEW_TEXT\|*`, other Mailchimp-feature conditions | `{% if false %}` (IFNOT → `{% if true %}`) |
| `*\|UNSUB\|*`, `*\|UPDATE_PROFILE\|*` | unsubscribe token |
| `*\|ARCHIVE\|*` | `{{ email.view }}` |
| `*\|LIST:COMPANY\|*`, `*\|HTML:LIST_ADDRESS_HTML\|*`, `*\|LIST:ADDRESS\|*`, `*\|LIST:URL\|*` | `organization.*` |
| `*\|CURRENT_YEAR\|*`, `*\|DATE:Y\|*` | current year |
| `*\|MC:SUBJECT\|*` | the subject from meta.json |
| `*\|MC_PREVIEW_TEXT\|*`, `*\|REWARDS\|*`, `*\|HTML:REWARDS\|*` | `''` (preheader comes from meta.json) |

Needs a mapping: `*|FACEBOOK:PROFILEURL|*`, `*|TWITTER:PROFILEURL|*` (the client's real profile URLs),
`*|FORWARD|*` (no equivalent: `""`), `*|DATE:format|*` other than `Y` (`{{ sent_timestamp | from_timestamp('<strftime>') }}`),
merge tags with `:` in them, and `*|INTERESTED:Group:Name|*` conditions (a Bloomreach property or segment).
`mc:edit`, `mc:repeatable` attributes are ignored. Image host to rehost: `mcusercontent.com`, `gallery.mailchimp.com`.

## Salesforce Marketing Cloud (AMPscript, `%%…%%`)

Export: Content Builder → the email → *Preview and Test* → copy the HTML, or the HTML paste view.

| Source | Automatic translation |
|---|---|
| `%%FirstName%%`, `%%emailaddr%%` and other `%%Attribute%%` personalization strings | customer property |
| `%%=AttributeValue("Field")=%%`, `%%=v(Field)=%%` (no `@`) | customer property |
| `%%unsub_center_url%%`, `%%profile_center_url%%`, `%%subscription_center_url%%` | unsubscribe token |
| `%%view_email_url%%` | `{{ email.view }}` |
| `%%Member_Busname%%`, `%%Member_Addr%%` | `organization.name`, `organization.full_address` |
| `%%Member_City%%`, `%%Member_State%%`, `%%Member_PostalCode%%`, `%%Member_Country%%` | `''` (the full address is in `Member_Addr`); check the footer punctuation |
| `%%xtyear%%` | current year |

Needs a mapping: **every** `%%[ … ]%%` block and every `%%=…=%%` with `@variables` or functions. Typical patterns:

| AMPscript | Bloomreach Jinja |
|---|---|
| `%%[ SET @fn = AttributeValue("FirstName") IF Empty(@fn) THEN SET @fn = "there" ENDIF ]%%` then `%%=v(@fn)=%%` | block → `""`; `%%=v(@fn)=%%` → `{{ customer.first_name \| default('there', true) }}` |
| `%%[ IF @tier == "Gold" THEN ]%%` … `%%[ ELSEIF … ]%%` … `%%[ ELSE ]%%` … `%%[ ENDIF ]%%` | `{% if customer.loyalty_tier == 'Gold' %}` … `{% elif … %}` … `{% else %}` … `{% endif %}` |
| `%%=Lookup("DE","Field","Key",_subscriberkey)=%%`, `LookupRows`, `FOR @i = 1 TO RowCount(@rows)` | data extensions don't exist in Bloomreach: use a customer property, a catalog (`catalogs.<name>.item_by_id()`) or an aggregate; agree the source with the user |
| `%%=Format(@date, "MMMM d")=%%` | `{{ … \| from_timestamp('%B %-d') }}` |
| `%%=ProperCase(@x)=%%`, `Uppercase`, `Lowercase` | `\| title`, `\| upper`, `\| lower` |
| `%%=RedirectTo(@url)=%%` | the URL expression itself: `{{ … }}` |
| `%%=ContentBlockByKey("…")=%%` | the content block's HTML has to be supplied by the client |

`_subscriberkey`, `jobid`, `listid` and other system strings have no equivalent; ask what they were used for.
Tracking tags such as `<custom name="opencounter" type="tracking"/>` are dropped. Image hosts: `*.sfmc-content.com`, `*.exacttarget.com`.

## HubSpot (HubL, `{{ contact.* }}`)

Export: Marketing → Email → the email → *Actions* → *Export HTML* (classic) or copy the source of the web version.

| Source | Automatic translation |
|---|---|
| `{{ contact.firstname }}`, `.lastname`, `.email`, `.phone` | customer property |
| any other `{{ contact.<prop> }}` | `customer.<prop>` (map it in `custom_properties`) |
| `\|default("x")` inside those | `\| default("x", true)` |
| `{% if contact.x %}`, `{% elif %}`, `{% else %}`, `{% endif %}` | same in Jinja with the property rewritten |
| `{{ unsubscribe_link }}`, `{{ unsubscribe_link_all }}` | unsubscribe token |
| `{{ view_as_page_url }}` | `{{ email.view }}` |
| `{{ site_settings.company_name }}`, `.company_street_address_1`, `.company_domain` | `organization.*` (other address parts → `''`) |
| `{{ local_dt\|datetimeformat('%Y') }}` | current year |

Needs a mapping: `{% module %}`, `{% dnd_area %}`, `{% widget_block %}` (export the rendered email instead),
`{{ content.* }}`, `{{ company.* }}` (a customer property or project variable), personalization tokens with
`|datetimeformat` or other HubL-only filters. Image hosts: `*.hubspotusercontent*.net`, `hubspot.net`, `hs-sites.com`.

## Braze (Liquid, `{{${attribute}}}`)

Export: the campaign or Canvas message → HTML editor → copy the HTML.

| Source | Automatic translation |
|---|---|
| `{{${first_name}}}`, `${last_name}`, `${email_address}`, `${phone_number}` | customer property |
| `{{custom_attribute.${x}}}` | `customer.<custom_properties[x]>` |
| `\| default: 'x'` | `\| default('x', true)` |
| `\| upcase`, `\| downcase`, `\| strip`, `\| truncate: n` | `\| upper`, `\| lower`, `\| trim`, `\| truncate(n)` |
| `{% if ${x} != blank %}`, `{% if ${x} == blank %}`, `{% elsif %}`, `{% unless %}` | `{% if x %}`, `{% if not x %}`, `{% elif %}`, `{% if not … %}` |
| `{{${set_user_to_unsubscribed_url}}}`, `{{${email_unsubscribe_url}}}` | unsubscribe token |

Needs a mapping: `{% connected_content %}` (no equivalent: use a catalog, aggregate or webhook node; agree with the
user), `{% catalog_items %}` (→ `catalogs.<name>.item_by_id()`), `{% abort_message %}` (→ a scenario condition
before the send; map the tag to `""` and report it), `{% assign %}` (→ `{% set %}`), `{{event_properties.${x}}}`
(→ `{{ event.x }}` with an event trigger), `{{campaign.${...}}}`, `{{canvas.${...}}}`. Image hosts: `braze-images.com`, `appboy-images.com`.

## Iterable (Handlebars, `{{firstName}}`)

Export: Templates → the template → *HTML source*.

| Source | Automatic translation |
|---|---|
| `{{firstName}}`, `{{lastName}}`, `{{email}}`, `{{phoneNumber}}` | customer property |
| any other `{{field}}` | `customer.<custom_properties[field]>` |
| `{{defaultIfEmpty firstName "there"}}` | `{{ customer.first_name \| default('there', true) }}` |
| `{{#if x}}` `{{else}}` `{{/if}}`, `{{#unless x}}` `{{/unless}}` | `{% if %}` / `{% else %}` / `{% endif %}`, `{% if not %}` |
| `{{unsubscribeUrl}}`, `{{unsubscribeMessageTypeUrl}}`, `{{hostedUnsubscribeUrl}}` | unsubscribe token |
| `{{viewInBrowserUrl}}` | `{{ email.view }}` |

Needs a mapping: `{{#each items}}…{{/each}}` (→ `{% for item in … %}` over an event list, aggregate or catalog),
`{{#ifEq a b}}`, `{{dateFormat …}}`, `{{[catalog lookups]}}` and data feeds (`[[ ]]` syntax: a catalog or webhook),
`{{{triple}}}` with HTML (same value, print it as is).

## ActiveCampaign (`%FIRSTNAME%`)

Detected only when the export looks like ActiveCampaign, so `100%` in copy or CSS is never mistaken for a tag.

| Source | Automatic translation |
|---|---|
| `%FIRSTNAME%`, `%LASTNAME%`, `%EMAIL%`, `%PHONE%`, `%FULLNAME%` | customer properties |
| other `%PERS_FIELD%` | `customer.<custom_properties[pers_field]>` |
| `%UNSUBSCRIBELINK%`, `%UPDATELINK%` | unsubscribe token |
| `%WEBCOPY%` | `{{ email.view }}` |
| `%SENDER-INFO%`, `%SENDER-INFO-SINGLELINE%` | `organization.name` + `organization.full_address` |

Needs a mapping: `%FORWARD2FRIEND%`, `%SOCIALSHARE%` (→ `""`), conditional content blocks (exported as
`{% if %}`-like markup in some accounts: translate by hand). Image host: `*.activehosted.com`.

## Klaviyo

Use the `convert-klaviyo-email-to-bloomreach` skill instead: it reads Klaviyo's block structure (desktop/mobile
variants, `{% catalog %}` loops, coupons) far more faithfully. The analyze report says so in `recommended_skill`.

## Plain HTML or another ESP

No tokens are translated automatically except Bloomreach-style ones already in the source (`{{ customer.* }}`,
`{{ event.* }}` and so on, which are kept). Every other `{{ }}`, `{% %}` or ESP tag is listed for mapping.
For an unknown ESP, ask the user which platform it came from, then translate each token by meaning.

## Adding or improving an ESP

The ESP rules live in three places in `scripts/html_email_to_bloomreach.py`, so a fork for one ESP only touches these:

1. `ESP_SIGNALS`: regexes that identify the ESP (counted; the highest count wins, `--esp` overrides).
2. `token_re()`: the token shapes that are cut out of the HTML before parsing.
3. `Translator.known()`: the automatic translations. Return `None` for anything that needs a human decision,
   so it lands in `mapping.tokens` instead of being guessed.

Add a synthetic fixture for the ESP to `tests/fixtures/engagement/html-email/` and a case to
`tests/engagement/test_convert_html_email_to_bloomreach_html_email_to_bloomreach.py`, then update this file.
