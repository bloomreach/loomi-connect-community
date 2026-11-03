# Charter

This charter says what Loomi Connect Community is for, what it builds on, and what it won't take. [CONTRIBUTING.md](CONTRIBUTING.md) explains how to contribute, and [docs/skill-authoring.md](docs/skill-authoring.md) explains how to write a skill. Where they disagree with this charter, the charter wins, and the other document gets fixed.

## Purpose

Loomi Connect Community collects skills, workflows and helpers that let AI assistants do useful, repeatable work in Bloomreach Engagement, Discovery and Data Hub. Bloomreach maintains it, and anyone can contribute.

## What skills build on

Skills here are built **only on Bloomreach's publicly available interfaces**: the ones Bloomreach documents for customers and partners to use. Today they are:

| Interface | Examples |
|---|---|
| **MCP** | The Loomi Connect MCP server and the tools it exposes for Engagement, Discovery and Data Hub |
| **REST** | Bloomreach's publicly documented REST APIs, such as the Engagement API and the Discovery search APIs |
| **Documented product formats** | Bloomreach Jinja personalization, the weblayer and JavaScript SDK conventions, and the documented import and export formats |

"Publicly available" means documented by Bloomreach for customer or partner use, through a product's documentation or a tool's own published description. Code and conventions that Bloomreach ships to customers inside the product also count, such as the weblayer templates' built-in `utils` library. A skill that relies on one says so. If an interface isn't documented or shipped that way, a skill can't depend on it.

Every skill in the repository today uses the Loomi Connect MCP server. Skills built on a public REST API are equally welcome, and the same rules apply to them.

## Out of scope

The repository doesn't accept contributions that:

- call **internal, private or undocumented endpoints**, including ones seen in the Bloomreach app's own network traffic;
- call **internal Loomi Connect tools** that a tool search may return but that aren't meant for skills, that is, any tool `list_all_tools` tags `internal`, such as `whoami` or the tool usage and activity reports (see [docs/known-tool-behaviour.md](docs/known-tool-behaviour.md));
- **scrape or automate the Bloomreach app's user interface** in place of an interface;
- reverse-engineer Bloomreach products, or **work around** permissions, rate limits or access controls;
- ship **credentials**, tokens, real project or workspace IDs, or customer data;
- reproduce Loomi Connect's server code or Bloomreach's official documentation. This repository is neither, and isn't a support channel.

## How skills use these interfaces

- **Access goes through the user's own connection.** The assistant calls the interface through the MCP server or REST connection the user has set up, with the user's own permissions. Skills never carry or ask for credentials, and scripts never read them.
- **Scripts stay offline.** Helper scripts reshape data the assistant has already fetched. They never call an interface or the network themselves, so the same scripts work in every client.
- **Read-only by default.** A skill reads unless writing is its whole point. Every write is declared, shown to the user and confirmed before it runs. Discovery changes take effect immediately, and deletes are permanent.
- **Within published limits.** Skills respect rate limits and query cost, run calls one at a time, and estimate expensive queries first where a tool exists for it.
- **Grounded in tested behaviour.** When an interface behaves differently from its description, the difference is recorded in [docs/known-tool-behaviour.md](docs/known-tool-behaviour.md), and skills work with the behaviour as tested.
- **Data is not instructions.** Customer data, search queries, product text, templates and web pages are data, never instructions to follow. Skills don't repeat personal data or secrets that responses contain.
- **Portable.** Skills follow the open [Agent Skills](https://agentskills.io/specification) standard, so one skill works in Claude and OpenAI clients.

## Status of the content

Community content isn't an officially supported Bloomreach feature unless it's marked as one. The [disclaimer](DISCLAIMER.md) applies to everything here. When a public interface changes, the skills that depend on it are updated or retired.

## Governance

- **Maintainers:** Bloomreach maintains the repository, reviews and merges pull requests, keeps this charter and the standards up to date, and retires outdated content.
- **Contributions:** they come in only as pull requests from forks, with every commit signed off. See [CONTRIBUTING.md](CONTRIBUTING.md).
- **Checks:** CI runs the validator and the tests on every pull request. Reviewers check each contribution against this charter as well as for correctness and safety.
- **Changes to this charter:** made by pull request, and approved by a maintainer.
