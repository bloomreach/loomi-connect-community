# Example: hidden configuration audit

Illustrative output for a made-up account. Every ID, name and value is invented.

**Prompt:** "Audit the audiences and API parameter overrides on our Discovery account."

## Discovery hidden configuration audit: contoso_apparel (2026-11-03)

**Summary:** 15 audiences (6 unused), 9 API parameter overrides (8 enabled). 6 high, 11 medium, 7 low.

### High
| Area | ID | Name | Issue | Evidence | Action |
|---|---|---|---|---|---|
| Audience | 102 | Promo mail | Can't match, so its rules never fire | Referral URL value `PromoMail ` has a trailing space. Enabled rule: 9003 ("spring dresses") | Remove the space, then check rule 9003 with discovery-change-qa |
| Audience | 100 | Top tier | Identical conditions to audience 101, both in use | `url` CONTAINS `seg=top-tier` on both | Keep 100, move 101's rule over, delete 101 |
| Audience | 112 | Contradiction | Can't match | Location IS `lyon` and IS NOT `lyon` | Rewrite the condition |
| Override | 502 | Debug left on | Overrides `br_diagnostics = all` on every request | Debug output on every live response | Disable it in the dashboard |
| Override | 503 | Black Friday rows | Expired but still enabled | `rows = 60` on every request | Disable it |
| Override | 501, 507 | Force price sort / Newest first | `sort` overridden twice | Two enabled overrides | Keep one |

### Low
| Area | ID | Name | Issue | Action |
|---|---|---|---|---|
| Audience | 103, 106, 109, 110, 111 | Retro Line, Test audience, … | Unused for over 30 days (103 can't match anyway) | Delete in the dashboard |
| Audience | 113 | Style formal | Only drives a disabled and an expired rule | Delete the rules and the audience, or re-enable |
| Override | 504 | Old experiment | Disabled since 2024 | Delete |

### Medium
| Area | ID | Name | Issue | Evidence |
|---|---|---|---|---|
| Audience | 104 | Short code | Short CONTAINS value | `ZZ` also matches URLs like `/buzz` |
| Audience | 108 | Gold | Overlaps audience 109 | `gold` also catches `gold_tier` visitors |
| Override | 501 | Force price sort | `sort = price asc` on every request | 2 enabled ranking rules may have no effect under it |

**Personalised rules:** "shirt" → rule 9001 → Top tier; "jeans" → rule 9002 → Top tier; "spring dresses" → rule 9003 → Promo mail.
**Protected (ask the owner):** audience 105 "Gift wrap - do not delete"; override 509 "keep - do not delete".
**Couldn't verify:** audience 113 depends on the Engagement segment "Style Preference"; one of its rules is a facet rule or redirect the lists don't show; override 505's parameters couldn't be read.
