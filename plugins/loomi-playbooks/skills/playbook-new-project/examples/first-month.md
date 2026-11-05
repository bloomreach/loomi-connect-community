# Example: the first month for a new customer

Illustrative only: the account, project, IDs and all numbers are made up.

**Session 1 (5 November).** "We've just started with acme (production) and project 1a2b3c. They went live last week. What's the plan for the first month?"

```
| Stage | Outcome | Headline |
|---|---|---|
| overview | oriented | 41 event types; the product view event is named product_view; 1.2M customers |
| readiness | not ready | 1 RED, 4 AMBER; by owner developer 3, merchandiser 1, CRM 1 |
| tracking | problems found | cart_update down 62% on the week; 14 junk event types |
| feeds | red | search-pageview: 100% of events flagged catalogs_required |
| catalog-config | high fixes | brand not searchable; an internal field is displayable |
| lifecycle | mapped | 3 of 8 flows live; biggest gap: win-back, about 4,100 a month |
```

The findings recorded along the way include:

```
- F1 (open, high): pixel search-pageview red; 100% of events flagged catalogs_required. Next: data-feed-health
- F2 (open, high): attribute brand not searchable. Next: discovery-catalog-config-audit
- F3 (open, high): flow win_back missing; about 2,000 a month in the audience, about 4,100 a month at stake. Next: playbook-lifecycle-gap
```

**The plan:**

```
| Week | Do | Owner | Evidence | Playbook or skill |
|---|---|---|---|---|
| 1 | Add the catalogs parameter to the search page pixel | developer | 100% of search page views flagged | data-feed-health |
| 1 | Find why cart_update fell 62% | developer | down on the week, other events steady | engagement-tracking-health |
| 2 | Make brand searchable; hide the internal field | merchandiser | High fixes in the catalog audit | discovery-catalog-config-audit, then playbook-findability |
| 2–3 | Build win-back, then browse abandonment | CRM | missing; about 4,100 a month at stake | playbook-lifecycle-gap |
| 3–4 | Dead-end searches and weak categories | merchandiser | once the search pixel is fixed | playbook-findability |
| 2–4 | Weekly triage every Monday | ecommerce | — | playbook-weekly-triage |
```

The run is finished; the plan's items are findings in the hand-off file, so the weekly triage sees them.
