# Using these skills with OpenAI

First connect Loomi Connect to your client: see [connecting-loomi-connect.md](connecting-loomi-connect.md).

OpenAI's clients follow the same open [Agent Skills standard](https://agentskills.io/specification) as Claude, so the skills in this repository work without changes. Codex and ChatGPT also read the optional `agents/openai.yaml` file in each skill, which holds the display name and the setting that controls whether the skill can run automatically.

## Codex (CLI, IDE extension, app): as plugins

This repository also works as a Codex plugin marketplace. The Codex manifests are in `.agents/plugins/marketplace.json` and in each plugin's `.codex-plugin/plugin.json`.

```bash
codex plugin marketplace add bloomreach/loomi-connect-community
```

Then install `loomi-engagement`, `loomi-discovery`, `loomi-platform`, `loomi-product-data` and `loomi-playbooks` from Codex's plugin directory. To get new versions:

```bash
codex plugin marketplace upgrade
```

## Codex: individual skills

Copy or symlink a skill folder into:

- `~/.agents/skills/<skill-name>/` for you only; or
- `.agents/skills/<skill-name>/` in a repository, for everyone working on it.

`./scripts/install-skills.sh` symlinks every skill into `~/.agents/skills/` for you.

Codex uses a skill automatically when your request matches its description. You can also call one directly with `$skill-name`, or browse them with `/skills`.

## ChatGPT

Skills are available on ChatGPT work plans, and your workspace admin must turn them on.

1. Zip the skill folder:
   ```bash
   cd plugins/loomi-engagement/skills && zip -r loomi-project-overview.zip loomi-project-overview
   ```
2. In ChatGPT, go to **Skills → Create → Upload from your computer**.
3. Use the skill by typing `@loomi-project-overview`, or just ask a question that matches it.

Your admin can also publish skills to the whole workspace.

## OpenAI API and Agents SDK

Upload a skill folder through `POST /v1/skills`, as a zip or as individual files. Then attach it to a shell tool environment in the Responses API, or to an Agents SDK sandbox. Limits: a 50 MB zip, at most 500 files, and exactly one `SKILL.md`. See [OpenAI's skills guide](https://developers.openai.com/api/docs/guides/tools-skills).

## Differences to be aware of

| | Claude | OpenAI |
|---|---|---|
| Personal skill folder | `~/.claude/skills/` | `~/.agents/skills/` |
| Project skill folder | `.claude/skills/` | `.agents/skills/` |
| Call a skill by name | `/skill-name` | `$skill-name` (Codex), `@skill-name` (ChatGPT) |
| Stop a skill running automatically | `disable-model-invocation` in frontmatter (Claude Code only) | `policy.allow_implicit_invocation: false` in `agents/openai.yaml` |
| `allowed-tools` | Pre-approves tools (Claude Code) | Not supported |
| Plugin manifest | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` |
| Marketplace file | `.claude-plugin/marketplace.json` | `.agents/plugins/marketplace.json` |

This is why the [authoring guide](skill-authoring.md) asks contributors to use only the shared spec fields in `SKILL.md`, and to put OpenAI-specific settings in `agents/openai.yaml`.
