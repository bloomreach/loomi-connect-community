# Loomi Connect Community — Project Brief

## Summary

Loomi Connect Community is an open repository of tools, skills and processes that help people get more out of **Loomi Connect**, the Bloomreach MCP server that gives AI assistants access to Bloomreach Engagement and Discovery.

Loomi Connect provides the raw capability: tools to query customers, events, campaigns, scenarios, reports, search performance, merchandising rules and more. This project collects the know-how on top of that: reusable skills, tested workflows, prompts and helper scripts that turn those tools into repeatable outcomes.

Bloomreach maintains the repository, and anyone can contribute: customers, partners, and Bloomreach staff.

The scope has since been set out in the [charter](../CHARTER.md): skills build on Bloomreach's publicly available interfaces, which include public REST APIs as well as Loomi Connect.

## Problem

Teams using Loomi Connect solve the same problems again and again, each on their own:

- Working out which tools to chain for a common task (for example: find a project → inspect the event schema → build a segment → check its size).
- Writing prompts and skills that reliably produce correct EQL, reports or campaign setups.
- Learning by trial and error which operations are safe, which are expensive, and which change live configuration.

Good solutions exist today, but they sit in individual laptops, Slack threads and customer workspaces. Nobody can find them, review them or improve them.

## Goals

1. **One place to find proven Loomi Connect assets.** A user should be able to browse the repo, pick a skill or workflow, and use it within minutes.
2. **Encourage community contribution.** Make it easy and safe for anyone to share what works for them.
3. **Keep the bar for quality and safety high.** Everything merged is reviewed, documented, and free of credentials and customer data.
4. **Feed learning back into the product.** Patterns that show up often in the community become candidates for first-party Loomi Connect features.

## Non-goals

- This is not the Loomi Connect server source code, and not its official documentation.
- It is not a support channel. Product issues still go through normal Bloomreach support.
- Contributions are not officially supported Bloomreach features unless they are clearly marked as such.

## What the repository will contain

| Type | Description | Example |
|---|---|---|
| **Skills** | Packaged instructions (Agent Skills standard) for a specific task using Loomi Connect tools | "Weekly campaign performance digest", "Audit Discovery ranking rules" |
| **Workflows / recipes** | Step-by-step tool sequences for common jobs, written as skills so the assistant can follow them | "Diagnose a drop in search conversion" |
| **Prompts** | Tested prompt templates for common questions | "Explain this scenario in plain English" |
| **Agent definitions** | Claude Code subagent configurations scoped to a role | "CRM analyst", "Merchandiser" |
| **Scripts & utilities** | Small helpers around Loomi Connect output (formatting, export, validation) | EQL linting, report-to-CSV |
| **Client setup guides** | How to connect Loomi Connect to different MCP clients | Claude Code, Claude Desktop, IDEs |
| **Examples & evals** | Sample inputs and expected outputs used to test that a contribution works | Test cases for a skill |

### Works with Claude and OpenAI

Skills follow the open [Agent Skills](https://agentskills.io/specification) standard, which Claude (Claude Code, claude.ai, the API) and OpenAI (Codex, ChatGPT, the API) both support. One skill folder works in every client.

The repository is also a **plugin marketplace for both Claude Code and Codex**, so users install with one command instead of copying files by hand:

```
/plugin marketplace add bloomreach/loomi-connect-community        # Claude Code
codex plugin marketplace add bloomreach/loomi-connect-community   # Codex
```

### Layout

```
loomi-connect-community/
├── .claude-plugin/marketplace.json     # Claude Code marketplace
├── .agents/plugins/marketplace.json    # Codex marketplace
├── plugins/
│   ├── loomi-engagement/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── .codex-plugin/plugin.json
│   │   ├── skills/<skill-name>/
│   │   │   ├── SKILL.md                # shared by all clients
│   │   │   ├── README.md
│   │   │   ├── agents/openai.yaml      # optional Codex/ChatGPT settings
│   │   │   ├── references/  scripts/  assets/  examples/
│   │   └── agents/                     # optional Claude Code subagents
│   └── loomi-discovery/                # same structure
├── templates/skill-template/
├── docs/                               # authoring and per-client usage guides
├── scripts/                            # validator, local install helper
└── .github/                            # PR/issue templates, CODEOWNERS, CI
```

Content is grouped into **plugins by product** (Engagement, Discovery) so users install only what they need. Workflows and prompt templates are written as skills, so the assistant can follow them directly. Helper scripts live inside the skill that uses them.

Each skill states in its frontmatter and README what it does, which Loomi Connect tools it uses, which products it covers, whether it **only reads** or **also writes**, and who maintains it.

The repository does **not** bundle the Loomi Connect server connection. The server URL varies by region and each user signs in themselves, so users connect it once, following `docs/connecting-loomi-connect.md`.

## Contribution model

We use the standard GitHub **fork → pull request → review → merge** flow. It is the only way submissions are accepted, for everyone including Bloomreach staff: contributors don't get write access to the repository, and changes sent by email, in issues or as attachments aren't accepted.

1. **Fork** the repository and create a branch.
2. **Add or change** the contribution, starting from `templates/skill-template/` and following `docs/skill-authoring.md`.
3. **Open a pull request** using the PR template. It asks the contributor to confirm:
   - no credentials, tokens, project IDs or customer data are included;
   - the contribution has been tested against a real or sandbox project;
   - any write operations are clearly labelled;
   - the automated validator (`scripts/validate_skills.py`, run in CI) passes.
4. **Review.** At least one maintainer reviews the PR for correctness, safety, clarity and fit. Contributions that change live configuration (for example Discovery rules, campaigns, scenarios) need a second reviewer.
5. **Merge.** A maintainer merges. The contributor is credited in the contribution's README.

Larger ideas, or anything that needs discussion first, start as a **GitHub issue** or discussion before any code is written.

Contributors agree that their work is licensed under Apache 2.0. *(Open question: do we also need a CLA or DCO sign-off? See below.)*

## Quality and safety standards

Loomi Connect can read sensitive customer data and change live configuration, so these rules are non-negotiable:

- **No secrets or customer data.** No API keys, tokens, real project or workspace IDs, customer records or screenshots of them. Use placeholders.
- **Read-only by default.** Contributions should read data unless writing is the whole point. Any write must be explicit and documented, and it should ask for confirmation before it runs.
- **Respect live-system behaviour.** Discovery writes take effect immediately and deletes are permanent. Contributions that touch them must say so at the top of their README.
- **Respect rate limits and cost.** Engagement tools share a per-user rate limit, and some analytics queries are expensive. Contributions should space out calls and estimate cost first where a tool exists for it (for example, estimating EQL cost before running a query).
- **Documented and tested.** Every contribution has a README, at least one worked example, and a note on which Loomi Connect version or tool set it was tested against.

## Roles

| Role | Responsibility |
|---|---|
| **Maintainers** (Bloomreach) | Review and merge PRs, keep standards up to date, triage issues, retire stale content |
| **Contributors** | Submit and improve content; maintain what they submit where they can |
| **Users** | Use the content, report problems, suggest improvements |

## Success measures

- Number of merged contributions, and how many come from outside the core team.
- Time from PR opened to first review.
- Usage signals: stars, forks, clones, and references from Bloomreach docs or customer conversations.
- Community patterns that get adopted into the Loomi Connect product.

## Phased plan

1. **Foundation** *(in place)*. README, CONTRIBUTING, Code of Conduct, security policy, PR and issue templates, skill template, authoring and per-client guides, Claude and Codex marketplaces, validator and CI.
2. **Seed content** *(started: one example skill per plugin)*. Bloomreach adds a first set of high-quality skills that cover Engagement and Discovery, to set the standard.
3. **Open to the community.** Announce to customers and partners, invite contributions, run the review process.
4. **Grow and curate.** Add more automated checks (for example secret scanning), tag and index content, and regularly retire outdated items.

## Open questions

- Is the repository public from day one, or internal or invite-only first?
- Do contributors need to sign a CLA, or is a DCO sign-off enough?
- Who are the initial maintainers, and what review turnaround do we commit to?
- How do we mark "Bloomreach-verified" content versus community content?
- How do we version contributions against changes to the Loomi Connect tool set?
- What is the official Loomi Connect server URL and setup page to link from `docs/connecting-loomi-connect.md`?
- Which GitHub team owns review (CODEOWNERS), and what contact handles Code of Conduct and security reports?
