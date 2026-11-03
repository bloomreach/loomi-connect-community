# Bloomreach REST sample connector

A small, **read-only** MCP server for a few of Bloomreach's public REST APIs, so you can try and test skills built on them. It's a sample, not a supported product: read `server.py` before you run it (it's about 300 lines of standard-library Python), and point it at a staging environment first.

It shows the pattern the [charter](../../CHARTER.md#secrets-and-keys) asks for: **your keys stay in your own client's configuration, and the assistant only ever sees tools.** See [docs/connecting-rest-apis.md](../../docs/connecting-rest-apis.md) for the general guide.

## Tools

| Tool | Public API | Keys it needs |
|---|---|---|
| `discovery_search` | Discovery [Product and Category Search API](https://documentation.bloomreach.com/discovery/reference) (`core.dxpapi.com`) | account ID and domain key; the private `auth_key` too, for server-side calls |
| `discovery_autosuggest` | Discovery [Autosuggest API](https://documentation.bloomreach.com/discovery/reference) (`suggest.dxpapi.com`) | account ID and domain key |
| `engagement_list_imports` | Engagement [Imports Management API](https://documentation.bloomreach.com/engagement/reference), list (GET) | project token, private API Key ID and API Secret |
| `engagement_get_import` | Engagement Imports Management API, one import (GET) | the same |

There are no write tools.

## What it does to keep your keys safe

- **Keys only come from environment variables.** They're never tool arguments; the server rejects any argument it doesn't expect.
- **Keys never come back.** Every result and error is checked for the configured secret values, in raw, URL-encoded and JSON-escaped form, and for the Basic-auth header built from them, and they're replaced with `[redacted]`. Fields that hold credentials in responses are blanked too: names like `password`, `pwd`, `auth`, `accessToken`, `clientSecret`, `api_key` and `connection_string`, header pairs such as `{"name": "X-Api-Key", "value": ...}`, user info in any URL (`mysql://user:pass@host`) and secret-looking URL parameters. That matters for imports, whose definitions can carry the credentials of the system they import from. Import source URLs lose their whole query string, which can hold signed tokens.
- **Only Bloomreach hosts, over https, GET only.** Discovery calls go to `core.dxpapi.com` and `suggest.dxpapi.com`. Engagement calls go to `https://api.exponea.com`, or the `https://` base URL you set, which must be on `exponea.com` or `bloomreach.com` (edit `ENGAGEMENT_DOMAINS` in `server.py` if your instance's API URL is elsewhere).
- **Redirects aren't followed,** so credentials are never sent to a second host.
- **Limits:** a 20-second timeout, a 2 MB response cap, at most 50 rows, and long results are cut.
- **No logs, no files.** It writes nothing to disk and prints nothing but MCP messages.

## Keys and settings

| Variable | For | Kind |
|---|---|---|
| `BLOOMREACH_DISCOVERY_ACCOUNT_ID` | Discovery tools | Public identifier |
| `BLOOMREACH_DISCOVERY_DOMAIN_KEY` | Discovery tools | Public identifier |
| `BLOOMREACH_DISCOVERY_AUTH_KEY` | `discovery_search` (server-side calls) | **Secret** |
| `BLOOMREACH_DISCOVERY_SITE_URL` | Discovery tools: the page URL sent as `url` and `ref_url` (default `https://www.example.com/`) | Setting |
| `BLOOMREACH_ENGAGEMENT_PROJECT_TOKEN` | Engagement tools | Identifier |
| `BLOOMREACH_ENGAGEMENT_API_KEY_ID` | Engagement tools | **Secret** |
| `BLOOMREACH_ENGAGEMENT_API_SECRET` | Engagement tools | **Secret** |
| `BLOOMREACH_ENGAGEMENT_BASE_URL` | Engagement tools, if your instance has its own API URL (default `https://api.exponea.com`) | Setting |

You only need the variables for the tools you use; a tool with a missing variable says which one to set.

**Use the least access that works:**

- **Engagement:** create a dedicated **private API group** for this connector (Project settings > Access management > API) and give it only the permissions the imports tools need. Don't reuse a key that can export customers.
- **Discovery:** create an API key scoped to your **staging environment** (Setup > Search API keys). Search calls from here may count as traffic in that environment's analytics.
- Rotate or revoke the keys when you're done testing. Both products let you do it in the UI.

## Set it up

**Give the keys to the server, not to your shell.** Don't export them in your shell profile: an AI client's own command tool usually inherits that environment, so one `env` command (perhaps prompted by text injected into data it read) would print them. Put the values in the server's own configuration instead, which only the server process receives.

That file is still readable by anything running as you, including an assistant's command tool. So also:

- use least-privilege keys for a staging environment (above), so a leaked key can do little;
- don't approve commands that read your client's configuration files or print the environment;
- rotate the keys when you finish testing, and straight away if one shows up in a chat.

### Claude Code

Add the server at user scope, so its configuration lives in your private user config rather than a project file:

```bash
claude mcp add --scope user bloomreach-rest-sample \
  -e BLOOMREACH_DISCOVERY_ACCOUNT_ID=<account id> -e BLOOMREACH_DISCOVERY_DOMAIN_KEY=<domain key> \
  -e BLOOMREACH_DISCOVERY_AUTH_KEY=<auth key> \
  -e BLOOMREACH_ENGAGEMENT_PROJECT_TOKEN=<project token> \
  -e BLOOMREACH_ENGAGEMENT_API_KEY_ID=<key id> -e BLOOMREACH_ENGAGEMENT_API_SECRET=<secret> \
  -- python3 /full/path/to/loomi-connect-community/connectors/bloomreach-rest-sample/server.py
```

Run it in a terminal outside any AI session, and clear it from your shell history afterwards (or start the line with a space if your shell is set to skip those). Leave out the variables for tools you don't need. Then run `/mcp` in Claude Code to check the server is connected.

Never put the values in a project `.mcp.json`: that file sits in the project folder and is easy to commit (this repo's `.gitignore` excludes it as a precaution).

### Codex

Add it to `~/.codex/config.toml`, with the values in the server's `env` table:

```toml
[mcp_servers.bloomreach-rest-sample]
command = "python3"
args = ["/full/path/to/loomi-connect-community/connectors/bloomreach-rest-sample/server.py"]

[mcp_servers.bloomreach-rest-sample.env]
BLOOMREACH_DISCOVERY_ACCOUNT_ID = "<account id>"
BLOOMREACH_DISCOVERY_DOMAIN_KEY = "<domain key>"
BLOOMREACH_DISCOVERY_AUTH_KEY = "<auth key>"
BLOOMREACH_ENGAGEMENT_PROJECT_TOKEN = "<project token>"
BLOOMREACH_ENGAGEMENT_API_KEY_ID = "<key id>"
BLOOMREACH_ENGAGEMENT_API_SECRET = "<secret>"
```

Keep `config.toml` private (`chmod 600 ~/.codex/config.toml`).

### Try it

Ask, for example: "Use discovery_search to show me the first 5 results for 'rain jacket'", or "List the imports in my Engagement project". If a key is ever pasted into the chat or shows up in a response, rotate it.

## Tests

The tests run offline against a fake local server (`BLOOMREACH_SAMPLE_LOOPBACK_URL`, honoured only with `BLOOMREACH_SAMPLE_TEST_MODE=1` and only for a `127.0.0.1` or `::1` address):

```bash
python3 -m unittest tests.connectors.test_bloomreach_rest_sample
```

They check the MCP handshake, that keys reach the API but never the client (even in errors), the redaction of import credentials, the host, method and redirect rules, the limits, and argument checks.
