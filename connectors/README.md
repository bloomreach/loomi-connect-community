# Sample connectors

Small MCP servers for Bloomreach's public REST APIs, for testing skills built on them. They're samples, not supported products: read the code before you run one, and use a staging environment.

Each one follows the [charter's rules for secrets and keys](../CHARTER.md#secrets-and-keys): keys come only from your own client's configuration, the assistant only sees tools, and keys never appear in results, errors or logs. [docs/connecting-rest-apis.md](../docs/connecting-rest-apis.md) explains the pattern.

| Connector | APIs | Access |
|---|---|---|
| [bloomreach-rest-sample](bloomreach-rest-sample/) | Discovery Product and Category Search, Discovery Autosuggest, Engagement Imports Management (list and read) | Read-only |

A new sample connector must be read-only unless it says otherwise, use only the standard library, read keys only from the environment, redact credentials from everything it returns, and have offline tests in `tests/connectors/`.
