# Project access review

Runs a periodic user-access review of Bloomreach Engagement projects for security and admin teams: one project, several, or every project in an organisation. It lists each project's users and role labels, classifies email domains as company, vendor or external (using the domains you give it), flags shared or generic accounts, test aliases, incomplete profiles and people with access to many projects, and returns an access-review table plus a list of removals, downgrades and confirmations for a person to action in the Bloomreach UI. It never changes access.

| | |
|---|---|
| **Products** | Engagement |
| **Access** | Read-only |
| **Loomi Connect tools** | `list_cloud_organizations`, `list_projects`, `list_project_users`, optionally `get_cloud_organization_details` |
| **Tested with** | Claude Code: `list_cloud_organizations`, `get_cloud_organization_details`, `list_projects` and `list_project_users` (one sandbox project) run live and read-only to confirm the fields returned. The script was tested on synthetic responses. Not yet run end to end as a single session or as an org-wide review across several projects, and not tested in an OpenAI client. |
| **Maintainer** | Bloomreach |

## Example prompts

- "Who has access to our production Engagement project?"
- "Run our quarterly access review across all our Bloomreach projects. Our domain is example.com."
- "Are there any external or shared accounts in our Engagement projects?"
- "Check these leavers against our Bloomreach project users."

See [examples/illustrative-review.md](examples/illustrative-review.md) for an example output. Every name, address and number in it is fictional.

## How it works

1. Asks for the scope, your company email domain(s) and any expected vendor or agency domains. It never guesses them.
2. Resolves the organisation and projects, then calls `list_project_users` for each project, one at a time.
3. Applies the checks in [references/review-checks.md](references/review-checks.md): personal webmail and external domains, vendor access, shared and generic accounts, test aliases, incomplete profiles, access to many projects, and leavers (if you supply a list). [scripts/access_review.py](scripts/access_review.py) builds the table from saved responses (standard library only, no network).
4. Returns a per-project summary, the access-review table and up to about 10 prioritised actions for an administrator.

## Notes and limitations

- **No permission levels.** `list_project_users` returns a `role` field, but it's a job-role label (Developer, Marketing Manager, Other...), usually empty, not an access level. The skill can't count administrators; it tells you to check permission levels in the UI.
- **No last-login data.** Loomi Connect returns no login or activity dates, so the skill can't find stale accounts by itself. Paste a leavers list or a last-login export from the UI and it will cross-check them.
- There's no account creation or last-login date in the data, so stale accounts are found from a leavers list or a last-login export, not from the tool.
- Shared-account detection is a name pattern, so it can miss shared accounts with personal-looking names and occasionally flag a real person.
- The output lists names and email addresses. Treat it as internal and confidential.
- The organisation and project tools have a stricter rate limit (about 1 request per second) than other Engagement tools.
