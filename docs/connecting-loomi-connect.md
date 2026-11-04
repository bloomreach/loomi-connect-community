# Connecting Loomi Connect

Every skill in this repository calls tools on the **Loomi Connect** MCP server. Connect the server to your client before installing any skills.

Loomi Connect is a remote MCP server that uses HTTPS and signs you in with OAuth. You need:

- the Loomi Connect server URL for your region; <!-- TODO: link to the official Bloomreach Loomi Connect setup page -->
- a Bloomreach account with access to the projects you want to use.

The names below (`loomi-connect`) are only examples. Skills don't depend on the name you choose.

## Claude Code

```bash
claude mcp add --transport http loomi-connect <LOOMI_CONNECT_MCP_URL>
```

Then run `/mcp` in a Claude Code session and sign in.

## claude.ai and Claude Desktop

Add Loomi Connect as a custom connector under **Settings → Connectors**, then sign in. Your organisation admin may need to allow it first.

## OpenAI Codex

Add the server to `~/.codex/config.toml`:

```toml
[mcp_servers.loomi-connect]
url = "<LOOMI_CONNECT_MCP_URL>"
```

Or use the CLI:

```bash
codex mcp add loomi-connect --url <LOOMI_CONNECT_MCP_URL>
codex mcp login loomi-connect
codex mcp list
```

To be asked before any write tool runs, set `default_tools_approval_mode = "writes"` in that server's section.

## ChatGPT

1. Turn on developer mode under **Settings → Apps & Connectors → Advanced**. Availability depends on your plan and your workspace admin.
2. Go to **Plugins**, select **+**, then **Add custom MCP server**.
3. Enter the Loomi Connect URL, set authentication to OAuth, and sign in.
4. Review the list of tools, then create the plugin.

## Check that it works

Ask the assistant: *"Using Loomi Connect, list my Bloomreach organisations and projects."* It should call `list_cloud_organizations` and `list_projects`.

## If a project doesn't work

- **"Project … not found in any organization":** each Loomi Connect server URL covers one region. A project in another region needs that region's server, added as a second connection.
- **HTTP 401 on one project while others work:** your account isn't a member of that project. A workspace role doesn't always include it; ask your Bloomreach admin to add you to the project.
