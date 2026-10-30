# Bloomreach Jinja reference

Read this before writing or fixing any Bloomreach Engagement Jinja. It covers the data objects you can use, the hard limits that break a template, the filters and syntax that are safe, and patterns that work.

Checked against the Bloomreach documentation on 2026-04-17 (pages: jinja, filters, jinjablocks, datastructures, personalization-using-jinja, useful-jinja-snippets, integration-of-recommendations, aggregates-and-running-aggregates, predictions, using-template-parameters, weblayer-design, jinja-syntax). The block and snippet sections were checked on 2026-10-30 against html-blocks, snippets and filters. `expressions` and direct `predictions(...)` calls aren't in the docs, but they work in practice.

All IDs and names in the examples below are placeholders. Replace them with real ones from the project.

---

## Data you can use

### Everywhere

| Object | What it is |
|---|---|
| `customer` | Customer attributes. Prefer bracket notation: `customer['first_name']` |
| `customer_ids` | Customer identifiers: `customer_ids.cookie`, `customer_ids.registered`, `customer_ids.email_id`, `customer_ids.phone_id` |
| `time` | The current Unix timestamp in seconds (a number) |
| `aggregates` | Aggregated datasets, keyed by aggregate ID. **Keys must be constant strings**: no variables, no template parameters |
| `catalogs` | `catalogs['catalog_name'].item_by_id(id)` and `catalogs['catalog_name'].items_by_id(id_list)`. At most 100 IDs per call |
| `recommendations(engine_id, size=10, fill_with_random=false, items={}, category_names=[], catalog_filter=[], cached=true)` | Returns a **generator** of recommended items. The engine ID must be a constant string or a `recommendation`-type template parameter (see hard limit 1). The first positional argument is the engine ID; the optional second positional argument is the count |
| `segmentations` | Keyed by segmentation ID; returns the customer's segment name |
| `metrics` | Keyed by metric ID |
| `reports` | Keyed by report ID. `reports['report_id'].rows` returns a nested array of rows |
| `report_value_by_key(report_id, row_value, column_value, metric_order)` | Looks up one value in a report. Usually easier than `reports[...].rows` |
| `project_variables` | Project variables by their Jinja reference name: `project_variables.JinjaReferenceName` (plural) |
| `block('block_id', {'paramName': value})` | Renders an HTML block from the Asset Manager. Returns rendered **text**, not Jinja objects (see "Passing data back from a block or snippet") |
| `snippet('snippet_id', {'paramName': value})` | Renders a snippet from the Asset Manager. Also returns rendered text |
| `expressions` | Analytics expression results (not in the docs, but works) |
| `predictions(prediction_id)` | Prediction lookup (not in the docs). The documented way is `customer['prediction_name']`, because predictions are stored as customer attributes |

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
{% set recs = recommendations("[[ { name: 'RecEngine', category: 'Recommendations', isJsonParam: true } : recommendation ]]", size=4, fill_with_random=true) | list %}

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

### 2. Generators: always `| list` before indexing, slicing or `| length`

These return **generators**, not lists:

- `recommendations(...)`
- `selectattr`, `rejectattr`
- `select`, `reject`
- `map`
- `batch`, `slice`

```jinja
{% set recs = recommendations('your_engine_id', size=4, fill_with_random=true) | list %}
{% set priced = recs | selectattr('price', 'greaterthan', 0) | list %}
{% set first_three = recs[:3] %}      {# only works after | list #}
{% set count = recs | length %}       {# only works after | list #}
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

- **Always** guard optional values with `| default(...)`:
  ```jinja
  {{ customer['first_name'] | default('there') }}
  {% set buyers = report_value_by_key('your_report_id', productId, 'purchase_count', 0) | default(0) | int %}
  ```
- **Cast types** before maths or comparisons: `| int`, `| float`, `| string`.
- **Check before you split** a string: `{% if 'key-' in s %}`.
- **An aggregate that returns `none` renders as the string `"None"`**, which is truthy. Guard with `{% if x and x != 'None' %}`, not just `{% if x %}`.
- **Prefer bracket notation** for attributes. `customer['first_name']` is safer than `customer.first_name`, because dot access fails on names that start with a digit, contain spaces or match a Python keyword.

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

**Core:** `default`, `int`, `float`, `string`, `abs`, `round`

**Strings:** `lower`, `upper`, `capitalize`, `title`, `replace`, `trim`, `truncate`, `striptags`, `urlencode`, `urldecode`, `remove_accents`, `escape` / `e`, `format`

**Lists:** `list`, `unique`, `length` / `count`, `first`, `last`, `join`, `sort`, `reverse`, `shuffle`, `sum`, `map`, `select`, `reject`, `selectattr`, `rejectattr`, `batch`, `slice`, `random`

**JSON:** `from_json`, and `json` to write safe JSON into JavaScript (use this, never `tojson`)

**Dates:** `to_timestamp`, `from_timestamp`

**Debugging:** `debug`, `pprint`. Remove them before anything goes live.

Price formatting: `{{ '%.2f' | format(item['price'] | float) }}`

---

## Patterns

### Recommendations: fetch, slice and loop

Numbers come from `[[ ... : number ]]` parameters through `{% set %}`. The engine ID goes inline, in double quotes, as a literal or a `recommendation` picker.

```html
{% set recCount = "[[ { name: 'RecCount', category: 'Recommendations', isJsonParam: true } : number | 4 ]]" | int %}
{% set recs = recommendations("[[ { name: 'RecEngine', category: 'Recommendations', isJsonParam: true } : recommendation ]]", size=recCount, fill_with_random=true) | list %}

{% if recs %}
  <div class="rec-grid">
    {% for item in recs %}
      <a href="{{ item['url'] }}" class="rec-card">
        {% if item['image'] %}<img src="{{ item['image'] }}" alt="{{ item['title'] | default('Product') }}">{% endif %}
        <div class="rec-name">{{ item['title'] | default('') }}</div>
        <div class="rec-price">{{ item['price'] | default('') }}</div>
      </a>
    {% endfor %}
  </div>
{% endif %}
```

Item fields (`url`, `image`, `title`, `price` above) come from the engine's catalog, so check the catalog's real field names.

For a hard-coded engine instead of a picker:

```jinja
{% set recs = recommendations('your_engine_id', size=recCount, fill_with_random=true) | list %}
```

**Skip some, then take some:**

```jinja
{% set skip = 3 %}
{% set take = 5 %}
{% set all = recommendations('your_engine_id', size=skip + take, fill_with_random=true) | list %}
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
{% set cart = aggregates['your_cart_aggregate_id'] if aggregates['your_cart_aggregate_id'] else [] %}

{% set ids = [] %}
{% for it in cart %}
  {% if it['product_id'] %}{% append it['product_id'] to ids %}{% endif %}
{% endfor %}

{% set items = catalogs['your_catalog_name'].items_by_id(ids) %}
```

Use `items_by_id(list)` rather than `item_by_id` inside a loop. Remember the limit of 100 IDs per call.

### Report value (social proof)

```jinja
{% set productId = "[[ { name: 'ProductID', category: 'Social proof', isJsonParam: true } : string ]]" %}
{% set buyers = report_value_by_key('your_report_id', productId, 'purchase_count', 0) | default(0) | int %}

{% if buyers > 0 %}
  <p>{{ buyers }} people bought this today</p>
{% endif %}
```

### Safe JSON into JavaScript

To pass data into a `<script>` block, use `| json`, never `tojson`:

```html
<script>
  var recs = {{ recs | json }};
  var cartIds = {{ ids | json }};
</script>
```

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

Don't invent filters, functions or objects that aren't in this file. If the user wants something this file doesn't cover, rewrite it with what's here. If that isn't possible, say plainly that Bloomreach Jinja doesn't support it, and explain the workaround you used.
