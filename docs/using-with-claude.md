# Using these skills with Claude

First connect Loomi Connect to your client: see [connecting-loomi-connect.md](connecting-loomi-connect.md).

Skills don't sync between Claude Code, claude.ai and the Claude API. Install them separately on each one you use.

## Claude Code: as plugins (recommended)

This repository is a Claude Code plugin marketplace.

```
/plugin marketplace add bloomreach/loomi-connect-community
/plugin install loomi-engagement@loomi-connect-community
/plugin install loomi-discovery@loomi-connect-community
/plugin install loomi-platform@loomi-connect-community
/plugin install loomi-product-data@loomi-connect-community
/plugin install loomi-playbooks@loomi-connect-community
```

From a shell:

```bash
claude plugin marketplace add bloomreach/loomi-connect-community
claude plugin install loomi-engagement@loomi-connect-community
claude plugin install loomi-discovery@loomi-connect-community
claude plugin install loomi-platform@loomi-connect-community
claude plugin install loomi-product-data@loomi-connect-community
claude plugin install loomi-playbooks@loomi-connect-community
```

To get new versions:

```
/plugin marketplace update loomi-connect-community
```

Claude uses a plugin's skills automatically when your request matches them. You can also call one directly by name, for example `/loomi-engagement:loomi-project-overview`.

## Claude Code: individual skills

To use a single skill without installing a plugin, copy or symlink its folder into:

- `~/.claude/skills/<skill-name>/` for you only, in every project; or
- `.claude/skills/<skill-name>/` for everyone working on one repository.

`./scripts/install-skills.sh` symlinks every skill into `~/.claude/skills/` for you.

## claude.ai and Claude Desktop

1. Zip the skill folder so that the folder itself is at the top of the zip:
   ```bash
   cd plugins/loomi-engagement/skills && zip -r loomi-project-overview.zip loomi-project-overview
   ```
2. In claude.ai, go to **Settings → Capabilities → Skills** and upload the zip.

Skills you upload are available only to you. Claude Code-only frontmatter fields are ignored here, which is one reason shared skills leave them out.

## Claude API and Agent SDK

Upload a skill folder through the Skills API (`/v1/skills`) and refer to it by `skill_id`. Skills on the API run **without network access**. That's fine for skills here, because Loomi Connect is reached through the MCP connection, not from inside the skill. See [Anthropic's Agent Skills docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview).

## Subagents

Plugins may also include Claude Code subagents in `agents/*.md`. These are Claude-only. In a subagent's `tools` list, Loomi Connect tools appear with your server's prefix, for example `mcp__loomi-connect__list_projects`. So contributed subagents should leave `tools` unset (the subagent inherits all tools) rather than guess your server name.
