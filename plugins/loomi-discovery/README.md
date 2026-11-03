# loomi-discovery

Skills for **Bloomreach Discovery** that use Loomi Connect.

> Discovery changes take effect immediately, and deletes are permanent. Skills that write here need two reviewers.

### Search

| Skill | What it does | Access |
|---|---|---|
| [discovery-search-health](skills/discovery-search-health/) | Search performance health check, with queries to investigate | Read-only |
| [discovery-trending-searches](skills/discovery-trending-searches/) | Rising, new and falling searches, adjusted for overall traffic | Read-only |
| [discovery-query-diagnosis](skills/discovery-query-diagnosis/) | Why one query underperforms, and fixes ranked by impact | Read-only |
| [discovery-product-visibility](skills/discovery-product-visibility/) | Why one product ranks low or is missing for a search or category: recall, merchandising rules, ranking signals or product data, with the smallest fix | Read-only |
| [discovery-search-category-match](skills/discovery-search-category-match/) | Compares search results for category-name queries with the category page; recommends a redirect, a ranking alignment or leaving it | Read-only |
| [discovery-zero-results-triage](skills/discovery-zero-results-triage/) | Sorts every dead-end query into synonym fix, catalog gap, redirect or noise | Read-only |
| [discovery-synonym-review](skills/discovery-synonym-review/) | Finds bad, risky or one-way synonyms, and leftover test synonyms | Read-only |
| [autosuggest-audit](skills/autosuggest-audit/) | Missing top searches, dead-end suggestions, weak wordings, exclusion candidates | Read-only |
| [facet-optimizer](skills/facet-optimizer/) | Junk, missing and messy filters on top search and category pages | Read-only |
| [discovery-redirect-audit](skills/discovery-redirect-audit/) | Broken, conflicting, hijacking and missing search redirects, with a prioritised fix list | Read-only |

### Categories, products and brands

| Skill | What it does | Access |
|---|---|---|
| [discovery-category-health](skills/discovery-category-health/) | Underperforming categories, broken dynamic categories, buried products | Read-only |
| [discovery-dynamic-category-review](skills/discovery-dynamic-category-review/) | Empty, overlapping, fragile and underperforming dynamic categories, with prioritised fixes | Read-only |
| [topic-collection-builder](skills/topic-collection-builder/) | Builds one collection for a named topic from search data plus companion products that go with it (shoes, eyewear for pickleball), with tested rules | Read-only |
| [product-opportunity-finder](skills/product-opportunity-finder/) | Products to fix, boost, bury or clear, with revenue at stake | Read-only |
| [brand-performance-review](skills/brand-performance-review/) | Brand scorecard comparing revenue share with exposure; range gaps; supplier conversations | Read-only |
| [new-arrivals-tracker](skills/new-arrivals-tracker/) | Are new products getting seen? Breakout, buried, slow-start and invisible new arrivals | Read-only |

### Rules and testing

| Skill | What it does | Access |
|---|---|---|
| [discovery-rule-audit](skills/discovery-rule-audit/) | Cleanup list of expired, duplicate, unused or conflicting merchandising rules | Read-only |
| [discovery-change-qa](skills/discovery-change-qa/) | Pre-launch QA of one ranking rule, synonym, redirect or banner rule: before/after preview, revenue at stake, clashes, with a go/no-go verdict | Read-only |
| [discovery-ranking-algorithm-review](skills/discovery-ranking-algorithm-review/) | Ranking Studio audit: which pages each algorithm ranks, broken, stuck, unused or duplicate algorithms, wrong page type, and weights worth a second look | Read-only |
| [discovery-hidden-config-audit](skills/discovery-hidden-config-audit/) | Audiences that can't match, overlap or go unused, which rules are personalised, and forgotten API parameter overrides | Read-only |
| [discovery-media-asset-cleanup](skills/discovery-media-asset-cleanup/) | Unused, stale, broken or hot-linked banners and in-grid assets, and media rule placements with missing assets or overlapping slots | Read-only |
| [discovery-api-health](skills/discovery-api-health/) | Did search break? Discovery API volume by request type, 4xx/5xx errors, staging traffic, and unique visitors against contract, red/amber/green with dates | Read-only |
| [discovery-experiment-readout](skills/discovery-experiment-readout/) | A/B test results in plain English: ship it, keep running or stop | Read-only |
| [discovery-experiment-setup](skills/discovery-experiment-setup/) | Guided A/B test for a ranking rule: preview, draft, then start | **Writes** |

Skills marked **Writes** only run when you call them by name, and ask for confirmation before every change.

To add a skill, see [CONTRIBUTING.md](../../CONTRIBUTING.md).
