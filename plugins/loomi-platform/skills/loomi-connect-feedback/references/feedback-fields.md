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
  "known_line": 127
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
| `arguments` | yes | The arguments as sent (`{}` if none). The script keeps only numbers, booleans, ISO dates and plain values of enum-like keys (`allowed_arg_keys` in [rules.json](rules.json), such as `filter_preset` or `sort`); every other value becomes a placeholder named after its key, lower case without `_` or `-` (`account_id` and `accountId` both become `<accountid>`). |
| `response_excerpt` | no | The smallest part of the response that shows the problem. If it's JSON, the script keeps numbers, booleans, dates and error or message text (redacted) and replaces every other string; otherwise it redacts it as free text. Leave out product, query and customer text anyway. |
| `what_i_tried` | no | The calls and workarounds tried. A default is written if empty. |
| `suggestion` | no | What would fix it: a parameter, a field, a description change. |
| `product` | no | `discovery`, `engagement` or `datahub`. |
| `known_line` | no | The line number from `list-known` when the problem is an item in docs/known-tool-behaviour.md. Needs `--known-doc`. |
| `client`, `model` | never | Not sent: the tool detects both itself, and free text there could leak a name. A report that sets them gets a warning that they're ignored. |

Placeholders are `<name>` in angle brackets: `<project_id>`, `<account_id>`, `<auth_key>`, `<email>`, `<url>`, `<id>`. Use them in `summary`, `expected`, `actual` and the other free text from the start. The script normalises every string (NFKC, invisible characters removed), redacts the free text and the quoted known-behaviour line, and then lints the final strings exactly as sent:

- **Hard leaks block the plan:** an email or anything with `@` or "at … dot", a URL, link target or host (only the repo's known-behaviour URL is allowed), a secret, token, cookie or `%3D`-encoded value, an ID, an IP address, a card number, an IBAN, a phone number, a private term.
- **Soft ones warn:** capitalised word pairs anywhere (sentence start included), capitalised words in quoted strings, tokens with several `_` or `-` parts that aren't tool or field names, unusual enum values in the arguments (`known_arg_values`), a word after "user", "by" and similar, money amounts and large figures, business figures, dotted names. They're listed in the confirmation, masked except the first letter.

This is best effort: it can't recognise every name, ID or business figure, so you read `payload_preview` and the user reads every field before it's sent.

**Private terms.** Always write `<work>/private-terms.txt` with your file-writing tool, one per line: the organisation, project, account, catalog and site names used in this session, and any customer, brand, site or person the user says must not appear. If none were used, write the `private_terms_none_line` from [rules.json](rules.json) instead; an empty file blocks the plan. Pass it with `--private-terms` (required). The script matches variants (case, and spaces, `_`, `.` or `-` between parts), replaces them everywhere, checks the `tool` field too, and blocks the plan if any are left.

## What the feedback text looks like

```
[Loomi Connect Community report] <tool>: <summary>

Product: <product> | Environment: <production or staging>

Expected: <expected>
Actual: <actual>

Minimal reproduction (IDs, names, emails, URLs and secrets replaced with placeholders):
  tool: <tool>
  arguments: {"account_id": "<accountid>", "days": 30, ...}

Response excerpt (placeholders as above):
<response_excerpt>

Recorded in the Loomi Connect Community repo's known tool behaviour (<section>, line <n>): <link>
> <the line, and its parent bullet if it has one>

Suggestion: <suggestion>
```

Sections without content are left out. `what_i_tried` goes in its own field. The plan's `payload_preview` shows `gap_type`, `completion_estimate`, this text and `what_i_tried` exactly as they'll be sent; the confirmation shows it verbatim.
