# Loomi Connect Community

**[Website](https://bloomreach.github.io/loomi-connect-community/) · [Quickstart](https://bloomreach.github.io/loomi-connect-community/quickstart.html) · [All skills](SKILLS.md)**

Community skills, workflows and tools for **Loomi Connect**, the Bloomreach MCP server that gives AI assistants access to Bloomreach Engagement, Discovery and Data Hub.

Loomi Connect provides the tools. This repository collects the know-how for using them well: tested skills, workflows and helpers that turn those tools into repeatable results. Bloomreach maintains it, and anyone can contribute.

Skills here are built only on the Loomi Connect MCP server. The [charter](CHARTER.md) sets out the scope.

Skills here follow the open [Agent Skills](https://agentskills.io/specification) standard, so the same skill works in **Claude** (Claude Code, claude.ai, the API) and **OpenAI** (Codex, ChatGPT, the API).

> Community content is not an officially supported Bloomreach feature unless it is marked as such. Read a skill before you run it, especially one that writes data. See the full [disclaimer](DISCLAIMER.md).

## What's here

**New here? Read [docs/skills-by-task.md](docs/skills-by-task.md).** It lists the skills by job: what to run every Monday, when something looks wrong, before a big event, and so on. For every skill in one list, see [SKILLS.md](SKILLS.md), or browse and search them on the [website](https://bloomreach.github.io/loomi-connect-community/).

| Plugin | What it covers |
|---|---|
| [`loomi-engagement`](plugins/loomi-engagement/) | Skills for Bloomreach Engagement: projects, customers, events, campaigns, scenarios, analytics |
| [`loomi-discovery`](plugins/loomi-discovery/) | Skills for Bloomreach Discovery: search and category performance, merchandising rules |
| [`loomi-platform`](plugins/loomi-platform/) | Skills that span products: weekly briefing and quarterly review, revenue anomalies, peak and go-live readiness, data and feed health, catalog parity, Data Hub collections and data retention, campaign planning, collections and change impact, and turning search demand into campaigns |
| [`loomi-product-data`](plugins/loomi-product-data/) | Product data for search engines and AI answers (SEO, AEO and GEO): find weak product data, suggest enhancements from images, attributes and shopper searches, and catch wrong prices and messy attribute values |
| [`loomi-playbooks`](plugins/loomi-playbooks/) | Playbooks that chain skills into one job, from finding a problem to fixing, testing and measuring it, across sessions: test and learn, findability, search demand to revenue, lifecycle gaps, catalog truth, revenue drops, peak events, weekly triage, quarter close and more |

Each plugin is a folder of skills under `skills/<skill-name>/SKILL.md`, plus a manifest for Claude (`.claude-plugin/`) and one for Codex (`.codex-plugin/`).

## Before you start: connect Loomi Connect

Every skill here calls Loomi Connect tools, so connect the Loomi Connect MCP server to your client first. See [docs/connecting-loomi-connect.md](docs/connecting-loomi-connect.md).

## Install

### Claude Code

```
/plugin marketplace add bloomreach/loomi-connect-community
/plugin install loomi-engagement@loomi-connect-community
/plugin install loomi-discovery@loomi-connect-community
/plugin install loomi-platform@loomi-connect-community
/plugin install loomi-product-data@loomi-connect-community
/plugin install loomi-playbooks@loomi-connect-community
```

More detail, including claude.ai and the API: [docs/using-with-claude.md](docs/using-with-claude.md).

### OpenAI Codex

```
codex plugin marketplace add bloomreach/loomi-connect-community
```

Then install the plugins from Codex's plugin directory. More detail, including ChatGPT and the API: [docs/using-with-openai.md](docs/using-with-openai.md).

### Without plugins

To link every skill into your personal skills folders for Claude Code (`~/.claude/skills`) and Codex (`~/.agents/skills`), run:

```bash
./scripts/install-skills.sh
```

The script symlinks the skills in your clone rather than copying them, so a `git pull` changes your installed skills straight away.

## Contributing

We welcome contributions. **All submissions are handled by forking this repository, making your changes in your fork, and opening a pull request.** Maintainers review every pull request before it's merged. We can't accept changes sent any other way. Every commit must be signed off with `git commit -s`; [CONTRIBUTING.md](CONTRIBUTING.md#sign-off) explains how.

Start with:

- [CHARTER.md](CHARTER.md): what the project builds on, and what's out of scope
- [CONTRIBUTING.md](CONTRIBUTING.md): the fork and pull request steps, and how review works
- [docs/skill-authoring.md](docs/skill-authoring.md): how to write a skill that works in Claude and OpenAI
- [templates/skill-template/](templates/skill-template/): the starting point for a new skill

## Safety

Loomi Connect can read customer data and change live configuration. Discovery changes take effect immediately, and deletes are permanent. Every skill in this repo:

- states whether it is **read-only** or **writes** data;
- asks before it makes any change;
- contains no credentials, real project IDs or customer data.

To report a security problem, see [SECURITY.md](SECURITY.md).

## Disclaimer

This repository is provided as is, without warranty, and is not covered by Bloomreach support. AI assistants can make mistakes, and you are responsible for any change made in your projects. Read the full [DISCLAIMER.md](DISCLAIMER.md).

## License

[Apache 2.0](LICENSE)
