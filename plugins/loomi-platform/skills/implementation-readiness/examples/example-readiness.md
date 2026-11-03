# Example: implementation readiness

**This example is illustrative.** The names and numbers are made up; the rows follow the script's output on synthetic fixtures. The pixel shape (API traffic arriving while the pixel sends nothing) was seen on a Bloomreach demo account.

**Prompt:** "We go live on 20 November. Is the Bloomreach setup ready?"

## Go-live readiness: example_outdoor / Example Outdoor (production)
Checked 2026-11-03 (prelaunch); launch 2026-11-20, 17 days to go.

**Verdict:** NOT READY: no checkout event is tracked and the Engagement product catalog is empty, so cart and purchase flows and recommendations can't work at launch.

### Blockers (fix before go-live)
| # | Area | Check | Evidence | Fix | Owner |
|---|---|---|---|---|---|
| 1 | Discovery catalog | product price filled | 75 of 100 sampled products (75%) with a numeric price | Fill price for every product in the feed | developer |
| 2 | Engagement tracking | event checkout | no checkout / begin_checkout event in the schema | Track checkout from the website (SDK) | developer |
| 3 | Engagement identity and consent | customer IDs | no hard (permanent) ID; soft IDs: cookie, registered | Make registered a hard ID and identify customers on login and purchase | developer |
| 4 | Engagement catalog | catalog items | 0 items | Run the catalog import | developer |

### Amber (fix or accept)
| # | Area | Check | Evidence | Fix | Owner |
|---|---|---|---|---|---|
| 1 | Discovery tracking | pixel conversion-pageview | no events in 24h | Add the conversion pixel to the order confirmation page, then check it in debug mode | developer |
| 2 | Discovery catalog | brand searchable | not searchable | Make brand searchable | merchandiser |
| 3 | Discovery search | category API traffic | no category requests over 7 days | Call the category API from staging and check it returns results | developer |
| 4 | Engagement tracking | event purchase | defined but never received | Send purchase from the site and check it arrives | developer |
| 5 | Engagement flows | cart abandonment flow | 1 found, none active (draft) | QA it (scenario-qa) and start it at launch | CRM |

### Green
- **Discovery tracking:** product, category and search page views; add-to-cart and search events; pixel issue rates under 1%
- **Discovery catalog:** feed and index jobs (daily, last success 3h ago); title and description searchable; 2 facetable attributes; title, URL and category filled
- **Discovery search:** search API traffic (3,200 requests in 7 days)
- **Engagement tracking:** session_start; view_item with product_id, price and title
- **Engagement identity and consent:** 2 consent categories (newsletter, sms)
- **Engagement catalog:** product catalog defined
- **Engagement flows:** welcome flow active

**Manual checks:** the site identifies customers on login, sign-up and purchase (developer); the sign-up form records newsletter consent (CRM); search and category pages render Bloomreach results on mobile (developer, merchandiser).
**By owner:** developer 7, merchandiser 1, CRM 1
