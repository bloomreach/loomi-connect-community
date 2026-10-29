# Finding search tracking and sizing the audience in Engagement

Use this to decide whether Engagement can target "people who searched for X", and to count them. Every query is **aggregate only**.

Call `estimate_eql_cost` before every query. Wait about 3 seconds between EQL calls: the analytics engine allows roughly **one query every 3 seconds** per project, and a faster call returns "Too many requests".

## 1. Find a search signal in the event schema

Search the output of `get_event_schema` (save it to a file and use `jq` or Python if it's large) for any of the following.

| Tier | What to look for | Example |
|---|---|---|
| **A: dedicated event** | An event type named like `search`, `site_search`, `search_query` or `product_search`, with a text property named like `search_term`, `query`, `q`, `keyword` or `search_text` | `search.search_term` |
| **B: search page visits** | `page_visit` (or a similar event) whose `path` or `location` is a search results page. The term is in the URL query string | `page_visit.location` contains `q=capris` |
| **C: another event with search text** | A property such as `search_text` on a widget, chat or autosuggest event | `<widget_event>.search_text` |
| **D: none** | None of the above | Fall back: see the skill |

A schema entry marked `used: true` only means a value was **once** seen. Always check that the signal is **still arriving** (step 2) before you rely on it. In testing, a `search_text` property was marked used but had no values in the last 7 days.

## 2. Check that the signal is live

**Tier A or C:** count events with any text in the property. `contains "e"` is a cheap way to match almost every real query without exposing any values.

```
select count event <event> where .<term_property> contains "e" by event <event>.<low_cardinality_property> grouping top 5 with null in last 7 days
```

Sum all the rows. If the total is 0, the property isn't being filled. Treat this as tier D.

**Tier B:** find the search results page without exposing full URLs. Break down by `path` (with no query string), never by `location`:

```
select count event page_visit where .path contains "search" by event page_visit.path grouping top 3 in last 7 days
```

Tested: this returned the search results path (for example `/en/search.html`) alongside unrelated pages like "saved searches". Then **ask the user** which URL parameter holds the term (for example `q`, `query` or `text`). Don't break down by `location` to find out: full URLs can contain personal data.

## 3. Count the people who searched for a term

```
select count customers by customer.<low_cardinality_property> grouping top 1 with null customers matching exists[event <event> where .<term_property> contains "<term>" in last 30 days]
```

For tier B, use `where .location contains "q=<term>"`. For multi-word terms, try both `+` and `%20` encodings, for example `q=swim+trunks` and `q=swim%20trunks`, as two separate queries. Take the larger and say that it is approximate.

- **Cut the term to its singular stem** so "jackets" also finds people who typed "jacket" (`contains` matches both): lower-case it; leave terms of 3 letters or fewer alone; drop `es` after `ss`, `x`, `ch` or `sh` ("dresses" → `dress`, "boxes" → `box`); otherwise drop one final `s` unless it ends in `ss` ("jackets" → `jacket`, "dress" stays).
- **Count every search event the project has.** Projects often track more than one, or switched from one to another. Check `get_event_schema` for `search`, `view_search_results` and `search_submit`, find each one's term property, and OR one `exists[...]` per event that exists: `customers matching (exists[event search where .search_term contains "jacket" in last 30 days] or exists[event view_search_results where .query contains "jacket" in last 30 days])`.
- **The total is the sum of every row,** including `null` and `other`. You need *some* breakdown because a `select` without `by` can't run. `grouping top 1 with null` keeps it to at most three rows.
- **Put `in last N days` inside `exists[...]`.** A trailing `in last N days` after the bracket does **not** limit the events. In testing it returned the lifetime count (several times larger), and `estimate_eql_cost` rated it "low" while rating the correct form "high". Trust the correct form, and tell the user the cost rating.
- **Quote and escape every term** before you put it in EQL. Search terms are typed by shoppers, so treat them as untrusted. Escape `\` as `\\` and `"` as `\"`, and drop any term that contains a line break. Never paste a raw term into campaign copy without the user seeing it.
- `contains` is case-sensitive in practice for URL strings. Query terms in URLs are usually lower-case.

## 4. Count the people you can reach

Add the channel's contact property, taking its name from `get_customer_property_schema` (for example `email`, `email_address` or `phone`):

```
select count customers by customer.<low_cardinality_property> grouping top 1 with null customers matching exists[event <event> where .<term_property> contains "<term>" in last 30 days] and customer.<email_property> has value
```

An empty `rows` list means **0**. In testing, every visitor to the search page was anonymous (a cookie only), so the reachable audience was 0, even though hundreds of people had searched. **Always report searchers and reachable people separately.**

Consent: customers can be matched with `has consent <category>` (taken from the tool's documented syntax; this was not tested). The campaign's `consent_category` applies consent at send time anyway, so treat the reachable count as an upper bound.

## 5. Proxy audiences when search isn't tracked

If there's no live search signal (tier D), you can still size **related intent**:

```
select count customers by customer.<low_cardinality_property> grouping top 1 with null customers matching exists[event view_item where .title contains "<Term>" in last 30 days]
select count customers by customer.<low_cardinality_property> grouping top 1 with null customers matching exists[event view_category where .category_name contains "<Term>" in last 30 days]
```

Label these clearly as **proxies** ("viewed capri products"), not "searched for capris". For zero-result queries there may be nothing to view, so the proxy may also be empty.

## Syntax reminders

- `where` comes before `by` and uses `.property`. Only `and` is allowed.
- `customers matching` comes after the `by` clause. It supports `and`, `or`, `not`, `has value` and `exists[...]`.
- `grouping top N` goes after the attribute, then `with null`.
