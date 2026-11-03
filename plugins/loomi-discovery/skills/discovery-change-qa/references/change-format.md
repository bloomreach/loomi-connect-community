# Describing the change for change_preview.py

`--change` takes one of these.

## A saved Loomi Connect record (an existing, disabled or draft rule)

Save the tool's result as it came back and pass the file:

| Change | Tool result to save |
|---|---|
| Ranking rule (boost, bury, pin, add to recall, attribute boost or bury) | `get_ranking_rule` with the rule's ID |
| Redirect | `search_redirects` with `rule_id` |
| Facet rule | `get_facet_rule` (`customizationItems` with `always_included_facets` and `excluded_facets`) |
| Synonym | One record from `list_synonyms_user`, saved on its own as a JSON object |

The script unwraps the `result` and `data` layers itself.

## A proposed change, written by hand

When the change doesn't exist yet, write it as a JSON object. Use only the keys you need.

```json
{
  "type": "ranking",
  "name": "Holiday dresses - boost Acme",
  "id": null,
  "queries": [{"query": "dress", "queryType": "sitesearch", "matchType": "EXACT_MATCH"}],
  "startedAt": "2026-11-20T00:00:00Z",
  "endedAt": "2026-12-01T00:00:00Z",
  "promotional": true,
  "boost_product_ids": ["<pid>"],
  "bury_product_ids": ["<pid>"],
  "product_slots": [{"product_id": "<pid>", "slot": 1}],
  "add_to_recall": ["<pid>"],
  "attribute_boost_bury": [{"type": "boost", "name": "brand", "values": ["Acme"], "strength": 40}]
}
```

| Key | Notes |
|---|---|
| `type` | `ranking`, `synonym`, `redirect`, `facet` or `media` |
| `id` | The rule's ID when the change edits an existing rule, so the script doesn't report it as clashing with itself |
| `queries` | `queryType`: `sitesearch`, `category` (the query is the category ID), or a global type (`global`, `sitesearch_global`) with query `*`. `matchType`: `EXACT_MATCH` or `PHRASE_MATCH` |
| `startedAt`, `endedAt` | ISO dates, or epoch milliseconds as the rule tools return them. Leave out for no schedule |
| `promotional` | Optional. Without it, a name containing a word from `promo_words` in `rules.json` counts as promotional |
| `attribute_boost_bury` | `values` are exact facet values. Number ranges look like `[50 TO *]` |

Other types:

```json
{"type": "synonym", "source": "frock", "targets": ["dress"], "two_way": false}
{"type": "redirect", "name": "Gift cards", "url": "https://<site>/gift-cards",
 "queries": [{"query": "gift cards", "queryType": "sitesearch", "matchType": "EXACT_MATCH"}]}
{"type": "facet", "queries": [...], "always_included": ["brand"], "excluded": ["margin"]}
{"type": "media", "name": "...", "queries": [...], "slots": [3], "image_url": "https://<cdn>/banner.png"}
```

For a synonym, `source` is what shoppers type and `targets` are what it also searches for. A one-way synonym `frock` → `dress` makes a search for "frock" also find dresses.
