# Loomi Connect feedback

Turns a Loomi Connect tool problem into a clear, privacy-safe report and sends it to the Loomi Connect team with `submit_llm_feedback`, after you confirm. The problem can be one you just hit (a tool that errored, returned wrong or missing data, disagreed with its description, or a capability that doesn't exist), or one of the items marked **(bug?)** in [docs/known-tool-behaviour.md](../../../../docs/known-tool-behaviour.md), which the skill lists for you to pick from.

This is the [charter](../../../../CHARTER.md)'s route for missing capabilities: when a skill needs data or an action Loomi Connect doesn't offer, the answer is to ask the Loomi Connect team to add it, not to reach Bloomreach another way.

| | |
|---|---|
| **Products** | Discovery, Engagement |
| **Access** | **Writes**: sends one feedback report to the Loomi Connect team (`submit_llm_feedback`) per confirmation. Nothing in Bloomreach changes. Never sends the (bug?) list in one go, never resends without a new yes, and never calls any other write tool or internal tools such as `get_llm_feedback_report` |
| **Loomi Connect tools** | `submit_llm_feedback` (write); `search_tools` only to check a tool's name or description |
| **Other requirements** | Python 3 for `scripts/tool_feedback_report.py` (standard library only). The (bug?) list needs this repository's `docs/known-tool-behaviour.md` (a local copy works) |
| **Tested with** | Claude Code: the payload follows `submit_llm_feedback`'s schema and description (fields, `gap_type` values, length limits, rate limit). The script was tested on synthetic data and on the repository's known-behaviour file. **No report was sent while building the skill.** Not yet tested in an OpenAI client |
| **Maintainer** | @bloomreach |

## Example prompts

- "`get_discovery_category_performance_table` just returned 0 rows with the lowest_converting preset. Report it to the Loomi Connect team."
- "Which of the known (bug?) items haven't we reported yet? Let me pick one to send."
- "There's no tool to read frequency caps per campaign. Ask Loomi Connect to add one."

See [examples/zero-rows-preset.md](examples/zero-rows-preset.md) for illustrative output.

## How it works

1. **Pick one problem:** from this session, or from `tool_feedback_report.py list-known`, which lists the (bug?) items with their section, the tools they name and a link to the line.
2. **Write the report file:** tool, one-line summary, gap type, completion estimate, expected versus actual, the arguments as sent, and optionally a short response excerpt and a suggestion ([references/feedback-fields.md](references/feedback-fields.md)).
3. **Build and lint:** `tool_feedback_report.py build` replaces every ID, account or project name, email, URL, `auth_key`, token and other secret in the arguments and the excerpt with placeholders such as `<project_id>`, writes the feedback text (with the environment, client and the known-behaviour link), and blocks it if anything personal or secret-shaped is left anywhere, if a field is over the tool's length limit, or if the same report was already sent.
4. **Confirm and send:** shows the whole report and waits for a yes, then sends it once.
5. **Read the response:** `tool_feedback_report.py verify` reports `accepted` (with an ID if one comes back), `rejected` (nothing recorded) or `unknown` (may have been recorded; not resent). Loomi Connect has no tool to read a sent report back, so this is the tool's response only.

## Notes and limitations

- **No read-back.** `submit_llm_feedback` is the only feedback tool skills may use. Reading past reports (`get_llm_feedback_report`) is internal, so a duplicate can't be found once sent. The skill keeps a local sent log (`--sent-log`) so it won't send the same report twice.
- **Rate limit.** One report every 10 seconds and 20 an hour.
- **Privacy.** The script replaces placeholders in the arguments and the response excerpt, but it doesn't rewrite your words: anything personal or secret-shaped left in the summary, expected, actual or other text blocks the report until you change it. Names it can't recognise (a customer or brand) are blocked only if you list them as private terms.
- **Keep the repo doc in step.** When you add a new quirk, or the Loomi Connect team confirms a fix, update [docs/known-tool-behaviour.md](../../../../docs/known-tool-behaviour.md) by pull request: add the quirk, or remove the **(bug?)** mark or the item once it's fixed.
- **Plan file.** The plan uses the shared plan-file shape (docs/skill-authoring.md) with `environment` and no account or project, because a report isn't tied to one. Its `undo` is empty: a sent report can't be withdrawn.
