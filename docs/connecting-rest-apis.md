# Connecting Bloomreach's public REST APIs

Most skills here use Loomi Connect, which you sign in to. Bloomreach also publishes REST APIs for every product, and a skill may build on those too (see the [charter](../CHARTER.md)). REST APIs use keys, so this guide says how to connect one without the keys ever reaching the assistant, the chat or this repository.

## The pattern

1. **You run a connector**: an MCP server for the API, in your own client. The keys go in that server's own configuration, never in your shell profile, which the assistant's command tool would inherit.
2. **The assistant sees tools**, such as `discovery_search`, never the keys.
3. **Skills call those tools** by name, like any Loomi Connect tool, and never ask for, store or pass keys.

[connectors/bloomreach-rest-sample](../connectors/bloomreach-rest-sample/) is a small read-only sample connector for testing: Discovery search and autosuggest, and Engagement imports. Start there.

Two ways that don't work:

- **Pasting a key into the chat.** It ends up in transcripts and the AI provider's logs. If it happens, rotate the key.
- **Having the assistant run `curl` with the key in an environment variable.** The assistant can print its environment, and this repo's scripts never call the network.

A connector's configuration file is still readable by anything running as you, so the backstop is least access (below), not approving commands that read client configuration or print the environment, and rotating keys.

## Two kinds of credential

| Kind | Examples | How to treat it |
|---|---|---|
| **Public identifiers** | Engagement project token and *public* API token (tracking, SDK); Discovery `account_id` and `domain_key` | Embedded in storefronts by design. Configuration, not secrets, but never commit real ones |
| **Secrets** | Engagement *private* API Key ID and API Secret; Discovery API keys and `auth_key`; Content management tokens | Only the connector holds them. Never in the chat, a file, a log or the repo |

## Least access

- **Engagement:** give each connector its own private API group with only the permissions its tools need ([Authentication](https://documentation.bloomreach.com/engagement/reference/authentication)). A read-only connector gets a read-only group.
- **Discovery:** scope API keys to an environment, and keep separate keys for staging and production ([Search API keys](https://documentation.bloomreach.com/discovery/reference/api-key-management)).
- Rotate keys regularly, and revoke them when you stop testing.

## The public APIs

Bloomreach documents these REST APIs ([documentation.bloomreach.com](https://documentation.bloomreach.com/)):

| Product | APIs |
|---|---|
| **Engagement** | Tracking, Customer, Catalog, Analysis, Email, SMS, External Segments, Imports Management, Managed Endpoints, Channel API for partners |
| **Discovery** | Product and Category Search, Autosuggest, Content Search, Recommendations and Pathways, Bestseller, Just For You, More Like This, Email Widget, Widget, Thematic, SEO, Site-crawl Content Search, Catalog Management, Catalog Data Management |
| **Data Hub** | Workspace, Item Collections, Unified Tracking |
| **Content** | Delivery (documents, folders, images, assets) and Management (content, content types, folders, projects, sites, webhooks, integrations, batch import and export) |
| **Clarity** | Conversational agent API |

## Writing a skill on a REST API

Follow [skill-authoring.md](skill-authoring.md#skills-built-on-a-rest-api). In short: name the API and the connector tools in the README and `compatibility`; if the tools aren't connected, stop and point the user to this guide; never ask for a key; and confirm every write, exactly as for Loomi Connect.
