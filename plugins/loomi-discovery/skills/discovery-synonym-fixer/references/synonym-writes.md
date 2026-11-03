# How the synonym write tools behave

Read this before the first write. It comes from the tools' published descriptions and the `discovery-synonyms` guide (`get_guide('discovery-synonyms')`). Before writing, read each tool's current schema with `search_tools`, and stop if it differs from what's below.

## The tools

| Tool | What it does | Notes |
|---|---|---|
| `create_synonym` | Creates a user synonym | One-way: `source_synonym` is what shoppers type, `target_synonym` is the comma-separated expansion, `group_synonym: false`. Two-way: every term comma-separated in `source_synonym`, `target_synonym` empty, `group_synonym: true`. `enabled` defaults to `true` |
| `update_synonym` | Changes terms, direction or enabled state of a synonym from `list_synonyms_user` | **`group_synonym` defaults to `false` and `enabled` to `true`.** Leaving either out silently turns a two-way synonym one-way, or switches a disabled synonym on. Always send `source_synonym`, `target_synonym`, `group_synonym` and `enabled`, which is what the plan's payloads do |
| `delete_synonym` | Deletes a synonym from `list_synonyms_user` | Permanent for a **User Created** synonym. For a **User Modified** synonym (a Bloomreach-generated one someone edited or disabled), it doesn't delete: the synonym moves back to the Bloomreach-generated list and is **re-enabled** with its generated terms |

All three take `account_name`, `environment` (`production` or `staging`) and, for a site-level synonym, `site_group_id`. The guide recommends account-level synonyms (no `site_group_id`), and always account level on multisite accounts. The guide says `delete_synonym` needs `confirmed=True`; the schema seen when this skill was written had no such parameter. Pass it only if the current schema has it, and only after the user's yes.

## Constraints

- Each term has at most `max_words_per_term` words, no quotes. Capitalisation doesn't matter.
- One-way needs at least one target; two-way needs at least two terms and no target.
- Only **User Created** synonyms can change direction.
- **Bloomreach-generated synonyms** (`list_synonyms_br_generated`) can't be changed with these tools: their IDs aren't in `list_synonyms_user`, and `update_synonym` refuses a synonym it can't find there. To switch one off, the user disables it in the Discovery dashboard; it then becomes User Modified and this skill can manage it. A user synonym for the same term applies alongside it; it doesn't replace it.
- Production and staging keep **separate synonym sets**. Every response has `environment_used`; check it, because staging-only accounts always use staging.

## Timing

Synonym changes sync about **once an hour** in production. A write shows in `list_synonyms_user` straight away, but search results change only after the next sync. Tell the user when to check, and check search then (`discovery-synonym-review`'s step 5, or the grid for the source and target terms).

## Undo

| Change | Undo |
|---|---|
| Create | `delete_synonym` with the new ID (a User Created synonym, so the delete is complete), or disable it with `update_synonym` |
| Update, enable, disable | `update_synonym` with the old values, all four fields |
| Delete of a User Created synonym | `create_synonym` with the old values. It gets a new ID |
| Delete (revert) of a User Modified synonym | Not possible with these tools. The user disables it again in the dashboard. Prefer disabling to deleting |
