# Example: Discovery API health

**This example is synthetic.** It's the report for the `broken` test fixtures in `tests/fixtures/discovery/api_health/`, for an invented account `example_store`. No real account, traffic or contract figures are shown.

**Prompt:** "Category pages and search looked wrong over the weekend. Is the Discovery API OK, and are we within our MUV contract?"

## Discovery API health: example_store, 31 Oct – 2 Nov 2026 against 3–30 Oct

**Overall:** RED: server errors hit 3% of requests on 1 November, and keyword search requests stopped completely on 2 November.

| Area | Series | Status | When | Evidence | Next step |
|---|---|---|---|---|---|
| Errors | 5xx | RED | 1 Nov | 2,400 server errors, 3.0% of requests (usually 0.01%) | Check the Bloomreach status page; raise a support ticket with the date |
| Volume | keyword search | RED | 2 Nov | no requests (usually about 30,000 on a Monday) | Ask the site team what changed; run `data-feed-health` to check the search pixel |
| Volume | site `uk` | RED | 2 Nov | 59% below its usual Monday volume | Check the UK site first; it's likely where keyword search broke |
| Errors | 4xx | AMBER | 2 Nov | 400 bad requests, 0.46% of requests: about 9× the usual share | The site may be sending broken requests since a release |
| Staging | staging share | AMBER | 2 Nov | 18% of requests went to staging (usually 1%) | Check which pages call the staging environment |
| Volume | autosuggest | AMBER | 2 Nov | 2.5× its usual volume | Possibly shoppers retrying while search was broken; check for bots |
| Volume | category | AMBER | 31 Oct | 30% below its usual Saturday | Watch; it recovered on 1 Nov |
| Volume | bestseller, other, total | GREEN | — | steady against the same weekdays | — |
| Contract | unique visitors | RED | Oct | 1,020,000 in October, 102% of the contracted limit; November forecast 94% | Tell the account owner and the Bloomreach account team |

**What this means:** search requests stopped on the UK site on 2 November, apparently after a site change that also sent traffic to staging and produced bad requests. Run `revenue-anomaly-explainer` for 2 November to size the revenue impact.
