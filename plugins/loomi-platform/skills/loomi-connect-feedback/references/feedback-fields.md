# Feedback fields

`tool_feedback_report.py build --report <work>/report.json` reads **one** problem object. Write it with your file-writing tool, never with `echo` or a redirect. A list is refused: one problem, one plan, one yes.

```json
{
  "tool": "get_discovery_category_performance_table",
  "product": "discovery",
  "summary": "filter_preset=lowest_converting returns 0 rows",
  "gap_type": "INCOMPLETE_DATA",
  "completion_estimate": 3,
  "expected": "The lowest-converting categories with enough traffic, as the description says.",
  "actual": "success: true with total_rows 0, while the same call without filter_preset returns rows.",
  "arguments": {"account_id": "<as sent>", "days": 30, "filter_preset": "lowest_converting"},
  "response_excerpt": "{\"success\": true, \"data\": {\"total_rows\": 0, \"rows\": []}}",
  "what_i_tried": "Called it with days 7 and 30, with and without filter_preset; sorted the unfiltered table instead.",
  "suggestion": "Apply the preset, or say in the description which accounts it works for.",
  "known_line": 127,
  "client": "claude-code"
}
```

| Field | Required | What to put |
|---|---|---|
| `tool` | yes | One published Loomi Connect tool name, plain (no client prefix). |
| `summary` | yes | One line: what goes wrong, in the tool's terms. At most `summary_max_chars` in [rules.json](rules.json). |
| `gap_type` | yes | `MISSING_TOOL` (no tool exists), `INCOMPLETE_DATA` (a tool exists but returned too little or wrong data), `AMBIGUOUS_RESULT` (the result couldn't be used with confidence) or `OTHER` (an error, a description that disagrees with behaviour, anything else). |
| `completion_estimate` | yes | How close the user got to what they asked for, on the tool's scale: 0 nothing useful, 1 found the problem but couldn't act, 2 context only, 3 partial with big gaps, 4 almost done, 5 fully done (rare in a problem report). The tool's description asks for it every time. |
| `expected` | yes | What the tool's description or schema led you to expect. |
| `actual` | yes | What came back, in your words. No customer data, names or URLs. |
| `arguments` | yes | The arguments as sent (`{}` if none). The script replaces IDs, account and project names, emails, URLs, `auth_key`, tokens and other secrets with placeholders such as `<project_id>`. Keep the other values (dates, presets, page sizes): they reproduce the problem. |
| `response_excerpt` | no | The smallest part of the response that shows the problem. URLs, emails, secrets and IDs are replaced; product, query and customer text isn't, so leave it out. |
| `what_i_tried` | no | The calls and workarounds tried. A default is written if empty. |
| `suggestion` | no | What would fix it: a parameter, a field, a description change. |
| `product` | no | `discovery`, `engagement` or `datahub`. |
| `known_line` | no | The line number from `list-known` when the problem is an item in docs/known-tool-behaviour.md. Needs `--known-doc`. |
| `client`, `model` | no | The tool detects both itself; give them only if detection is known to fail. |

Placeholders are `<name>` in angle brackets: `<project_id>`, `<account_id>`, `<auth_key>`, `<email>`, `<url>`, `<id>`. Use the same form in `summary`, `expected`, `actual` and the other free text: the script lints them and **blocks** anything personal or secret-shaped it finds there, rather than rewriting your words.

**Private terms.** If the user names a customer, brand, site or person who must not appear, write them one per line to `<work>/private-terms.txt` with your file-writing tool and pass `--private-terms`. Any of them left in the free text blocks the plan; in `arguments` and `response_excerpt` they're replaced with `<name>`.

## What the feedback text looks like

```
[Loomi Connect Community report] <tool>: <summary>

Product: <product> | Environment: <production or staging> | Client: <client>

Expected: <expected>
Actual: <actual>

Minimal reproduction (IDs, account and project names, emails, URLs and secrets replaced by placeholders):
  tool: <tool>
  arguments: {"account_id": "<account_id>", "days": 30, ...}

Response excerpt (placeholders as above):
<response_excerpt>

Recorded in the Loomi Connect Community repo's known tool behaviour (<section>, line <n>): <link>
> <the line, and its parent bullet if it has one>

Suggestion: <suggestion>
```

Sections without content are left out. `what_i_tried` goes in its own field.
