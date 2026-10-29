# EQL patterns for audience sizing

Use these to estimate how many customers match a definition. They're all **aggregate counts**: never list or read individual customers.

Status labels:
- **Ran:** executed successfully in live testing.
- **Parsed:** accepted by `estimate_eql_cost`, but not executed.

## The count query

A `select` needs a `by` breakdown to be executable. To get a single total, break down by any customer property with few values, include nulls, and **add up every row**:

```
select count customers by customer.<low_cardinality_property> grouping top 3 with null customers matching <conditions>
```

- Rows come back as `{"headers": [{"type": "single", "value": ...}], "values": [n]}`. There's also a row with `{"type": "other"}` for everything outside the top 3, and a row with value `null`. Add up **all** rows, including `null` and `other`, for the total. **(Ran)**
- **No matching customers returns an empty `rows` list**, not a row with 0. **(Ran)**
- Order inside `by`: attribute, then `grouping top N`, then `with null`.
- `customers matching ...` goes **after** the `by` clause.

## Conditions (`customers matching ...`)

Combine with `and`, `or`, `not` and parentheses.

| Audience wording | EQL | Status |
|---|---|---|
| Has ever done X | `exists[event purchase]` | Ran |
| Did X in the last N days | `exists[event purchase in last 90 days]` | Parsed |
| Did **not** do X in the last N days | `not exists[event purchase in last 30 days]` | Parsed |
| Bought in last 90 days but not in last 30 | `exists[event purchase in last 90 days] and not exists[event purchase in last 30 days]` | Parsed |
| Did X with a property condition | `exists[event purchase where .total_price > 100 in last 90 days]` | Parsed |
| Did X at least N times | `count event purchase in last 365 days >= 2` | Parsed |
| Customer property has a value | `customer.email has value` | Parsed |
| Customer property equals | `customer.country = "US"` | Parsed |
| Has consent for a category | `has consent <category_id>` (ID from `get_consent_settings`) | Parsed |
| Never did X | `not exists[event X]` | Parsed |

Other operators, from the tool documentation: `has no value`, `starts with`, `ends with`, `does not contain`, `matches regex`, `between X and Y`, `more than X days ago`, `id <identifier-field> <operator>`, `is in ["a", "b"]` (strings only, at least two items).

## Syntax traps (confirmed in testing)

- **Inside `exists[...]`, `where` must come before `in last`.** `exists[event purchase in last 90 days where .total_price > 100]` fails with "Unexpected token where".
- **The cost estimator does not check names.** A made-up property or event parses fine and gets an ordinary cost score. Check every property, event and event-property name against `get_customer_property_schema` and `get_event_schema` **before** estimating.
- Event-property filters use the `.property` shorthand (`where .total_price > 100`), not `event purchase.total_price`.
- In a top-level `where`, use only `and`. `or` and `not` belong in `customers matching`.
- Quote hyphenated property names: `customer."loyalty-tier"`, `."user-agent"`.
- `is null` isn't supported. Use `has no value`.
- ISO dates without `Z` are read as UTC.

## Cost

Always call `estimate_eql_cost` first. It returns `score` (0–100), `level` and `factors`.

- `low` or `medium`: run it.
- `high`: tell the user it's rated high cost and why (the `factors`), and run only if they agree. On large projects, even a plain lifetime customer count can be rated `high`, partly because the estimator ignores date windows inside `exists[...]`.
- `very_high`: don't run it. Event-based metrics (`select count event ...`) on large projects often land here. Rewrite as a customer count, or narrow it.
- A trailing `in last N days` at the very end of the query lowers the estimate, but its effect on a customer count wasn't confirmed in testing. Don't add it just to lower the cost score.

Analytics queries have their own rate limit, about **one every 3 seconds**, which is shared with other users of the same Engagement instance. On HTTP 429, wait 3–5 seconds and retry once.

## When the count is zero or surprising

1. Check that each name exists in the schema (the estimator won't catch typos).
2. Count each condition on its own, one query at a time, to find the one that empties the audience. Estimate the cost of each first.
3. Check whether the data is recent. In testing, a sandbox had purchases over its lifetime but none in the last 90 days, so every windowed condition returned zero. Compare `exists[event X]` with `exists[event X in last N days]`.
4. Say which it is: a definition problem, or simply no recent data.

## Sizing an existing customer filter

To size a filter that already exists, such as a scenario condition's `customer_filter`, run `scripts/filter_to_eql.py` (see SKILL.md step 6), which applies exactly these rules. By hand: translate each atom into a `customers matching` condition, then join them with its `formula`. Checked against a demo project.

| Atom | EQL |
|---|---|
| `attribute` / `property` with a string constraint | `customer."<property>" = "<value>"` (`equals`), `!=` (`does not equal`), `contains`, `does not contain`, `starts with`, `ends with` |
| same, number constraint | `=` (`equal to`), `!=`, `>`, `>=`, `<`, `<=` |
| same, boolean constraint (`operator: is`) | `= true` or `= false` (the value is the string `"true"` / `"false"`) |
| same, date constraint `more than` / `less than` with `amount`, `units`, `tense` | `more than <amount> <units> ago` (or `ahead`) |
| any constraint `has value` / `is set` | `has value`; `has no value` / `is not set` → `has no value` |
| `attribute` / `consent` with `category` | `has consent "<category>"`; with the value `"false"`, `not has consent "<category>"` |
| `attribute` / `id` with `id` (the identifier name) | `id "<identifier>" <comparison>` |
| `funnel_steps` with one step | `exists[event "<type>" where .<p> <cmp> and ... in last <n> <units>]` (drop `in last` when `date_filter.enabled` is false) |
| `funnel_steps` with several steps | `funnel("<a>" where ... followed by "<b>" ... in last <n> <units>)` |

Then rewrite the formula: `&` → `and`, `|` → `or`, `!` → `not`, then each `F<n>` becomes `(<atom n>)`. Rewrite the operators **before** putting the atoms in, or an atom's own `!=` and any `&`, `|` or `!` inside a value get rewritten too. An `F<n>` with no atom n becomes `(false)`. An empty formula or `1` means everyone. A formula with anything other than `F<n>`, `&`, `|`, `!`, brackets and spaces isn't one Engagement wrote: don't size it.

To give the audience as a share of everyone, count both in one query and add up each column over all rows: `select count customers matching <condition>, count customers by customer.<low_cardinality_property> grouping top 1 with null`.

Some atoms **can't be sized in EQL**, because they point at saved definitions by ID: `segmentation`, `prediction`, `aggregate`, `expression` and `embedded_aggregate` (an inline calculation). Event steps whose filters compare with another attribute can't either. For those, say the filter can't be counted outside Engagement and name which kinds of rule stop it. Don't size the rest of the filter on its own and present that as the answer: it would overstate the audience.

Quote names and values with double quotes, after removing any `"` or `\` from them and trimming spaces at the ends.
