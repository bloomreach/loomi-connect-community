# Example: integration inventory (illustrative)

**This example is illustrative.** The method and response shapes come from read-only live calls and synthetic tests, but the project, every name, host and number are invented. Nothing was changed, and no value, header, body or full URL is shown.

**Prompt:** "What integrations and API triggers do we have, and is anything unused or unsafe?"

---

## Integration inventory: Example Store (production), 2026-11-03

**Verdict:** 6 integrations, 4 API triggers and 7 project variables. The riskiest finding is a live scenario sending an access token in a webhook URL, and two project variables hold what look like credentials.

**Summary:** 6 integrations, 4 API triggers, 7 project variables, 2 webhook steps in 3 scenarios checked; 6 high, 10 medium, 8 low findings.

### Findings
| Priority | Area | Item | Finding | Action |
|---|---|---|---|---|
| High | Webhook | Order sync / step 2 | A credential is written into the URL query string (access_token) of a live scenario | Move it to an authentication integration or a header, and rotate it |
| High | Variable | partner_api_secret | Holds a value that looks like a credential | Move it to an authentication integration and rotate it |
| High | Variable | missing_var | Used in a live scenario but not defined, so it renders empty | Create the variable or fix the reference |
| High | API trigger | Legacy hook | Archived, but the active scenario "Legacy flow" listens to it | Unarchive it or move the scenario to another trigger |
| Medium | Webhook | Draft hooks / step 5 | Authenticates with an integration that doesn't exist; plain HTTP | Pick an existing integration; switch to HTTPS |
| Medium | API trigger | Untitled API trigger | No event type, and nothing listens to it | Check whether anything still calls it, then remove it |
| Medium | Integration | Mail provider / Mail provider (new) | Two email integrations with near-identical names | Find out which one sends, then remove the other |
| Low | Variable | logo_url, catalog_id | Not used in the 5 definitions checked | Check blocks and snippets before removing |

### Webhook steps
| Scenario (status) | Step | Description | Flags |
|---|---|---|---|
| Order sync (active) | Send order | An HTTP POST to hooks.partner.example with the authentication integration "CRM auth", an auth header and a credential parameter in the URL | Credential in URL; credential in step headers |
| Draft hooks (draft) | Old hook | An HTTP GET to plain.example over plain HTTP with an authentication integration that wasn't found and basic auth | Integration not found; empty credential parameter; plain HTTP |

**Not checked:** SMS campaigns (no access, HTTP 403); usage of the storage and delivery integrations (imports, exports and sending aren't visible); integrations' enabled state (not returned).
