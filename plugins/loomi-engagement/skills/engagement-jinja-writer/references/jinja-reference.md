# Bloomreach Jinja reference

Read this before writing or fixing any Bloomreach Engagement Jinja. It covers the data objects you can use, the hard limits that break a template, the filters and syntax that are safe, and patterns that work.

Checked against the Bloomreach documentation on 2026-04-17 (pages: jinja, filters, jinjablocks, datastructures, personalization-using-jinja, useful-jinja-snippets, integration-of-recommendations, aggregates-and-running-aggregates, predictions, using-template-parameters, weblayer-design, jinja-syntax). The block and snippet sections were checked on 2026-10-30 against html-blocks, snippets and filters. Reports, `default`, escaping and the filter list were checked on 2026-11-02 against filters and personalization-using-jinja. Only documented objects are listed (see CHARTER.md): use `customer['prediction_name']` for predictions.

All IDs and names in the examples below are placeholders. Replace them with real ones from the project.

---

## Data you can use

### Everywhere

| Object | What it is |
|---|---|
| `customer` | Customer attributes. Prefer bracket notation: `customer['first_name']` |
| `customer_ids` | Customer identifiers: `customer_ids.cookie`, `customer_ids.registered`, `customer_ids.email_id`, `customer_ids.phone_id`. Don't render hard IDs, email or phone into weblayer HTML or JavaScript globals unless the feature needs them |
| `time` | The current Unix timestamp in seconds (a number) |
| `aggregates` | Aggregated datasets, keyed by aggregate ID. **Keys must be constant strings**: no variables, no template parameters |
| `catalogs` | `catalogs['catalog_name'].item_by_id(id)` and `catalogs['catalog_name'].items_by_id(id_list)`. At most 100 IDs per call |
| `recommendations(engine_id, size=10, fill_with_random=false, items={}, category_names=[], catalog_filter=[], cached=true)` | Returns the recommended items, which you can index directly: `recommendations('your_engine_id', 4)[0]`. The engine ID must be a constant string or a `recommendation`-type template parameter (see hard limit 1). The first positional argument is the engine ID; the optional second positional argument is the count |
| `segmentations` | Keyed by segmentation ID; returns the customer's segment name |
| `metrics` | Keyed by metric ID |
| `reports('report_id')` | A whole report, called with round brackets: `reports('report_id').rows` returns a nested array of rows |
| `report_value_by_key(report_id, row_value, column_value, metric_order)` | Looks up one value in a report. `row_value` and `column_value` are values of the report's row and column breakdowns, not metric names. Pass `''` for a breakdown the report doesn't have. `metric_order` is the metric's 0-based position in the report (default 0). Usually easier than `reports('report_id').rows` |
| `project_variables` | Project variables by their Jinja reference name: `project_variables.JinjaReferenceName` (plural) |
| `block('block_id', {'paramName': value})` | Renders an HTML block from the Asset Manager. Returns rendered **text**, not Jinja objects (see "Passing data back from a block or snippet") |
| `snippet('snippet_id', {'paramName': value})` | Renders a snippet from the Asset Manager. Also returns rendered text |
| `customer['prediction_name']` | A prediction's score. Predictions are stored as customer attributes, so read them like any other attribute |

### Only in some places

| Object | Where it works |
|---|---|
| `event` | Event-triggered scenarios only: `event['total_price']`. Empty anywhere else, including weblayers |
| `vouchers['pool name'].assign_available()` | Emails and SMS. Add `cached=false` for a new code each time it's used. If the pool runs out, the email isn't sent |
| `consent.page` | Email unsubscribe link when the consent framework is on (`email.unsubscribe` is the legacy one). Only works in live sends, not test emails |
| `email.view` | "View in browser" link in emails |

### Template parameters are not Jinja

Weblayer and template parameters use `[[ ... ]]` syntax. Bloomreach swaps them for literal text **before** Jinja runs, so they aren't a Jinja object. To use a parameter's value in Jinja, assign it to a variable first:

```jinja
{% set recCount = "[[ RecCount : number | 4 ]]" | int %}
{{ recCount }}
```

The one exception is a recommendation engine picker, which goes straight into the `recommendations(...)` call (see hard limit 1).

---

## Hard limits: break one and the template breaks

### 1. IDs must be constant strings (aggregates, recommendations, dynamic keys)

Aggregate keys and recommendation engine IDs must be fixed when the template is parsed. The engine ID passed to `recommendations(...)` must be a **string literal**, so Jinja parses it and Bloomreach's validator accepts it. Two forms work:

1. A hard-coded literal: `recommendations('your_engine_id', ...)`
2. A `[[ ... : recommendation ]]` picker **wrapped in double quotes** at the call site: `recommendations("[[ { name: 'RecEngine', ... } : recommendation ]]", ...)`. Bloomreach puts the picked engine ID inside the quotes before rendering, so Jinja still sees a string literal.

Never assign the picker to a variable first, and never use it unquoted.

```jinja
{# OK: hard-coded literal #}
{% set recs = recommendations('your_engine_id') %}

{# OK: recommendation picker, inline and in double quotes #}
{% set recs = recommendations("[[ { name: 'RecEngine', category: 'Recommendations', isJsonParam: true } : recommendation ]]", size=4, fill_with_random=true) %}

{# NOT OK: unquoted picker. The { } and : break Jinja's tokenizer #}
{% set recs = recommendations([[ { name: 'RecEngine', ... } : recommendation ]]) %}

{# NOT OK: quoted but assigned to a variable. The validator sees a variable and rejects it #}
{% set engineId = "[[ ... : recommendation ]]" %}
{% set recs = recommendations(engineId) %}

{# NOT OK: any runtime variable #}
{% set id = 'your_engine_id' %}
{% set recs = recommendations(id) %}
```

Aggregate keys follow the same rule. There's no picker type for aggregates, so always use a literal:

```jinja
{# OK: literal aggregate key #}
{% set cart = aggregates['your_cart_aggregate_id'] %}

{# NOT OK: dynamic key #}
{% set id = 'your_cart_aggregate_id' %}
{% set cart = aggregates[id] %}
{% set cart = aggregates[customer['favourite']] %}
```

To switch between aggregates based on a parameter, map each option to a constant key with `if`/`elif`:

```jinja
{% set mode = "[[ Mode : enum(cart, wishlist) | cart ]]" %}
{% if mode == 'cart' %}
  {% set data = aggregates['your_cart_aggregate_id'] %}
{% elif mode == 'wishlist' %}
  {% set data = aggregates['your_wishlist_aggregate_id'] %}
{% endif %}
```

**The general rule:** the first key used to access any list, tuple, string or dict must be constant. To access one dynamically, wrap it in an extra list first: `[myDict][0][dynamicKey]`.

### 2. Filters that build lists return generators: add `| list` before indexing, slicing or `| length`

These filters return **generators**, not lists:

- `selectattr`, `rejectattr`
- `select`, `reject`
- `map`
- `batch`, `slice`

`recommendations(...)` itself doesn't need `| list`. Index it directly:

```jinja
{% set first = recommendations('your_engine_id', 4)[0] %}
{% set recs = recommendations('your_engine_id', size=4, fill_with_random=true) %}
{% set priced = recs | selectattr('price', 'greaterthan', 0) | list %}   {# the filter output needs | list #}
{% set first_priced = priced[0] %}                                        {# only works after | list #}
```

### 3. Loops: accumulate with `{% append %}`, not `{% set %}`

A variable you `{% set %}` inside a `for` loop is gone after the loop. To build a list:

```jinja
{% set ids = [] %}
{% for item in cart %}
  {% if item['product_id'] %}
    {% append item['product_id'] to ids %}
  {% endif %}
{% endfor %}
{# ids is usable here #}
```

Don't build or update dicts inside loops and expect the changes to stick.

### 4. Dates and times: no Python datetime

**Don't use** `strptime()`, `strftime()`, `datetime()`, `dateformat()` or anything else from Python's datetime. Use these filters instead:

```jinja
{# Date string to timestamp #}
{% set ts = "2026-04-17 14:30:00" | to_timestamp('%Y-%m-%d %H:%M:%S', timezone='UTC') %}

{# Timestamp to string: the format goes into from_timestamp #}
{% set pretty = ts | from_timestamp('%Y-%m-%d') %}
```

### 5. Functions and filters that don't work

Never use `merge()`, `update()`, `groupby()`, `max()`, `min()` or `tojson()`. Restructure with list accumulation, `if`/`elif` or plain loops instead.

### 6. Code defensively

- **Always** guard optional values with `| default(x, true)`. Without `true`, `default` only replaces undefined values, not `None` or `''`, so a customer with an empty first name gets "Hi None":
  ```jinja
  {{ customer['first_name'] | default('there', true) | e }}
  {% set buyers = report_value_by_key('your_report_id', productId, '', 0) | default(0, true) | int %}
  ```
- **Cast types** before maths or comparisons: `| int`, `| float`, `| string`.
- **Check before you split** a string: `{% if 'key-' in s %}`.
- **An aggregate that returns `none` renders as the string `"None"`**, which is truthy. Guard with `{% if x and x != 'None' %}`, not just `{% if x %}`.
- **Prefer bracket notation** for attributes. `customer['first_name']` is safer than `customer.first_name`, because dot access fails on names that start with a digit, contain spaces or match a Python keyword.

### 7. Escape values and check URLs: Bloomreach Jinja doesn't autoescape

Bloomreach Jinja has no automatic escaping (the filters docs say so under `safe`), so a catalog title, report value or customer attribute containing `<script>` or a stray quote is written into the page as it is. A bad product feed then becomes stored XSS on a live storefront.

- Use `| e` on every catalog, customer, report or aggregate value written into HTML text or an attribute.
- Escaping doesn't stop a `javascript:` URL. In `href` and `src`, only use URLs that start with `https://`, or relative paths that start with a single `/`. Anything else falls back to `#` or is left out:
  ```jinja
  {% set url = item['url'] | default('', true) | string | trim %}
  {% set url = url if url.startswith('https://') or (url.startswith('/') and not url.startswith('//')) else '#' %}
  <a href="{{ url | e }}">{{ item['title'] | default('', true) | e }}</a>
  ```
- For JavaScript, see "JSON into JavaScript" below.

---

## Syntax you can use

**Control flow:** `if` / `elif` / `else` / `endif`, `for` / `endfor`

**Loop variables:** `loop.index` (from 1), `loop.index0` (from 0), `loop.first`, `loop.last`, `loop.length`

**Assignment:** `{% set x = ... %}`

**Accumulation:** `{% append item to list %}`

**Comments:** `{# ... #}`, or `{#- ... -#}` to trim whitespace

**Strings:**
- Join: `a ~ b`
- Methods: `.split()`, `.replace()`, `.startswith()`, `.endswith()`
- Slicing: `s[1:5]`

**Error handling:**
```jinja
{% try %}
  ...
{% except %}
  ...
{% endtry %}
```

**Whitespace control:** `{%- ... -%}` inside HTML attributes, URLs or JavaScript, so no stray spaces end up in the output.

---

## Filters you can use

This list follows the Bloomreach filters page. If a filter isn't here, check that page before telling the user it isn't supported.

**Core:** `default` / `d` (use `default(x, true)`), `int`, `float`, `string`, `abs`, `round`, `attr`, `filesizeformat`

**Strings:** `lower`, `upper`, `capitalize`, `title`, `center`, `indent`, `replace`, `trim`, `truncate`, `wordwrap`, `wordcount`, `striptags`, `urlencode`, `urldecode`, `urlize`, `remove_accents`, `escape` / `e`, `forceescape`, `format`, `xmlattr`

**Encoding and hashing:** `b64encode`, `b64decode`, `hexencode`, `hexdecode`, `hash(hash_fn)` (md5, sha1, sha224, sha256, sha384, sha512), `hmac(msg=..., hash_fn=...)`

**Lists and dicts:** `list`, `unique`, `length` / `count`, `first`, `last`, `join`, `sort`, `dictsort`, `reverse`, `shuffle`, `sum`, `map`, `select`, `reject`, `selectattr`, `rejectattr`, `batch`, `slice`, `random`

**JSON:** `from_json`, and `json` to write data into JavaScript (use this, never `tojson`). `json` isn't documented to escape `</script>`, so see "JSON into JavaScript" below

`safe` exists but does nothing, because nothing is autoescaped.

**Dates:** `to_timestamp`, `from_timestamp`

**Debugging:** `debug`, `pprint`. Remove them before anything goes live.

Price formatting: `{{ '%.2f' | format(item['price'] | float) }}`

---

## Patterns

### Recommendations: fetch, slice and loop

Numbers come from `[[ ... : number ]]` parameters through `{% set %}`. The engine ID goes inline, in double quotes, as a literal or a `recommendation` picker.

```html
{% set recCount = "[[ { name: 'RecCount', category: 'Recommendations', isJsonParam: true } : number | 4 ]]" | int %}
{% set recs = recommendations("[[ { name: 'RecEngine', category: 'Recommendations', isJsonParam: true } : recommendation ]]", size=recCount, fill_with_random=true) %}

{% if recs %}
  <div class="rec-grid">
    {% for item in recs %}
      {% set url = item['url'] | default('', true) | string | trim %}
      {% set url = url if url.startswith('https://') or (url.startswith('/') and not url.startswith('//')) else '#' %}
      {% set img = item['image'] | default('', true) | string | trim %}
      <a href="{{ url | e }}" class="rec-card">
        {% if img.startswith('https://') %}<img src="{{ img | e }}" alt="{{ item['title'] | default('Product', true) | e }}">{% endif %}
        <div class="rec-name">{{ item['title'] | default('', true) | e }}</div>
        <div class="rec-price">{{ item['price'] | default('', true) | e }}</div>
      </a>
    {% endfor %}
  </div>
{% endif %}
```

Item fields (`url`, `image`, `title`, `price` above) come from the engine's catalog, so check the catalog's real field names.

For a hard-coded engine instead of a picker:

```jinja
{% set recs = recommendations('your_engine_id', size=recCount, fill_with_random=true) %}
```

For a single item, index the call: `{% set rec1 = recommendations('your_engine_id', 4)[0] %}`.

**Skip some, then take some:**

```jinja
{% set skip = 3 %}
{% set take = 5 %}
{% set all = recommendations('your_engine_id', size=skip + take, fill_with_random=true) %}
{% set shown = all[skip:skip + take] %}
```

### Aggregate: get IDs, then fetch them from the catalog in one call

What an aggregate returns depends on its type and attribute, so check its definition first. A `last` aggregate on a list property such as `cart_update.product_ids` returns that list of IDs directly:

```jinja
{% set raw = aggregates['your_cart_aggregate_id'] %}
{% set ids = raw if raw and raw != 'None' else [] %}
{% set items = catalogs['your_catalog_name'].items_by_id(ids[:100]) if ids else [] %}
```

An aggregate over whole objects, such as `cart_update.product_list`, returns a list of dicts. Collect the IDs first:

```jinja
{% set raw = aggregates['your_cart_aggregate_id'] %}
{% set cart = raw if raw and raw != 'None' else [] %}

{% set ids = [] %}
{% for it in cart %}
  {% if it['product_id'] %}{% append it['product_id'] to ids %}{% endif %}
{% endfor %}

{% set items = catalogs['your_catalog_name'].items_by_id(ids[:100]) if ids else [] %}
```

Use `items_by_id(list)` rather than `item_by_id` inside a loop. Remember the limit of 100 IDs per call.

### Report value (social proof)

Read the report's definition first (with Loomi Connect, `search_reports` with its `report_id`): its row breakdown, column breakdown and metric order decide the arguments. This example assumes rows broken down by product ID, no column breakdown (so `''`), and the purchase count as the first metric (so `0`):

```jinja
{% set productId = "[[ { name: 'ProductID', category: 'Social proof', isJsonParam: true } : string ]]" %}
{% set buyers = report_value_by_key('your_report_id', productId, '', 0) | default(0, true) | int %}

{% if buyers > 0 %}
  <p>{{ buyers }} people bought this today</p>
{% endif %}
```

### JSON into JavaScript

To pass data into a `<script>` block, use `| json`, never `tojson`. The docs don't say `json` escapes `</script>`, so a value containing it could end the script early. Replace `<` with its JSON escape, and pass only the fields the code needs, not whole catalog items:

```html
{% set recData = [] %}
{% for item in recs %}
  {% append {'id': item['item_id'], 'title': item['title']} to recData %}
{% endfor %}
<script>
  var recs = {{ recData | json | replace('<', '\\u003c') }};
  var cartIds = {{ ids | json | replace('<', '\\u003c') }};
</script>
```

In the browser, write these values into the page with `textContent` or `setAttribute`, never `innerHTML`, and check links start with `https://` first.

### Passing data into a block or snippet

Use parameters. Inside the block or snippet, read them with `params.paramName`, or with `params['param name']` for names with spaces or names that clash with dict methods such as `items`. When you call it, pass Jinja variables directly, without `{{ }}`. Use `~` to build strings:

```jinja
{{ block('your_block_id', {'products': ids, 'mainText': 'Hello ' ~ customer['first_name'] }) }}
```

`list` and `object` parameter types accept Jinja lists and dicts as they are, so data going in doesn't need JSON. Parameters can't contain `{% %}` logic.

Contextual variables (`event`, `webhook`, `email.view`) aren't available inside blocks or snippets. Pass them in as parameters from the campaign.

### Passing data back from a block or snippet

A block or snippet returns rendered text, not Jinja objects. If one builds data for the caller to use, such as a list of products, a dict or a count, have it output that data as JSON, then turn it back into data with `| from_json` where it's called:

```jinja
{# In the block or snippet: output only the JSON #}
{{- my_data | json -}}
```

```jinja
{# Where it's called: parse it back into a list or dict #}
{% set my_data = block('your_block_id') | from_json %}
{% set my_data = snippet('your_snippet_id', {'count': 4}) | from_json %}
```

- **Output nothing but the JSON.** Any HTML, text or Jinja comment the block renders breaks `from_json`. Trim whitespace with `{{- -}}` and `{%- -%}`.
- **Visual Builder rows wrap the output in HTML.** If you include a data block in a Visual Builder row, capture it and strip the tags before parsing. Use the row's "before" code `{%- set my_data %}` and its "after" code `{%- endset %}{%- set my_data = my_data | striptags | from_json %}`. Applying a filter on the `{% set %}` block tag itself isn't supported, so parse in a separate `{% set %}`. `striptags` also strips anything tag-like inside string values, so keep HTML out of the data.
- **Guard against an empty result:** `{% if my_data %}` before you use it.
- **No nesting:** a block can't call another block, and a snippet can't call another snippet.
- **Webhooks can't use blocks** (`block` isn't defined there). Use a snippet instead.
- **Limit:** at most 20 different snippets in one campaign template or block.

---

## Weblayers

- Jinja goes in the HTML and JavaScript of a weblayer.
- In CSS, keep Jinja to `{% set %}` lines at the top that turn parameters into variables, then `{{ varName }}` where they're used. Don't put data lookups in CSS.
- `event` is empty in weblayers. Use aggregates or customer attributes instead.

---

## When something isn't supported

Don't invent filters, functions or objects. If one isn't in this file, check the Bloomreach filters and personalization docs before saying it's unsupported. If the user wants something this file doesn't cover, rewrite it with what's here. If that isn't possible, say plainly that Bloomreach Jinja doesn't support it, and explain the workaround you used.
