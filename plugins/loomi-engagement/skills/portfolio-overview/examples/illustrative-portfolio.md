# Illustrative output

Every name and number below is fictional.

## Engagement portfolio: Example Agency, 2026-11-04

**Verdict:** 10 projects: 6 green, 1 amber, 2 red and 1 unknown. Brand Bravo has had no events for 7 days and no live scenarios.

| Project | Workspace | Customers | Events | Event types | Score | Band | Flags |
|---|---|---|---|---|---|---|---|
| Brand Golf | Brands | - | - | - | - | unknown | overview unavailable |
| Brand Bravo | Brands | 80,000 | 8,560,000 | 6 | 35 | red | no live scenarios, no recent events |
| Brand Echo | Brands | 0 | 0 | - | 40 | red | no events |
| Brand Delta | Brands | 500 | 53,500 | 6 | 75 | amber | outlier (low), small customer base |
| Brand Charlie | Brands | 120,000 | 12,840,000 | 6 | 80 | green | shrinking customers, fewer events |
| Brand Alpha | Brands | 100,000 | 10,700,000 | 6 | 85 | green | busy event types silent |
| Brand Hotel | Brands | 90,000 | 9,630,000 | 5 | 85 | green | no campaign events |
| Brand India | Brands | 60,000 | 64,200,000 | 6 | 95 | green | outlier (high) |
| Contest Hub | Brands | 70,000 | 7,490,000 | 6 | 100 | green | none |
| Fox Test Sandbox | Brands | 2,000 | 214,000 | 6 | 100 | green | test or sandbox |

**Portfolio:** 10 projects, 522,500 customers, 113.7 million events; median 80,000 customers and 107 events per customer across 7 comparable projects.

### Needs attention
| # | Project | Problem | Priority | Next step |
|---|---|---|---|---|
| 1 | Brand Bravo | No events in the last 7 days | High | Run engagement-tracking-health on Brand Bravo |
| 2 | Brand Bravo | No active scenarios | High | Run lifecycle-coverage-map on Brand Bravo |
| 3 | Brand Echo | No events stored at all | High | Run engagement-tracking-health; confirm the project is still needed |
| 4 | Brand Alpha | page_visit and view_item silent for 7 days | Medium | Run engagement-tracking-health on Brand Alpha |
| 5 | Brand Charlie | Customers fell from 150,000 to 120,000 since 2026-08-01 | Medium | Run engagement-tracking-health; check retention or a deletion |
| 6 | Brand Hotel | Has never recorded a campaign send | Medium | Run lifecycle-coverage-map on Brand Hotel |
| 7 | Brand Delta | 500 customers, far below the portfolio | Medium | Run loomi-project-overview to see what it's for |

### Not checked
- Recent activity and live scenarios: deeper mode ran on Brand Alpha, Brand Bravo and Brand Charlie only.
- Brand Golf: the overview couldn't be read.

**Deeper mode:** 6 more projects could be checked (18 calls). Say which, or "the next five".
