# Illustrative output

Every name, ID and number below is fictional.

## Media cleanup: Example Shop (production), 2026-11-04

**Verdict:** 9 files and 8 reusable assets checked: 4 files are unused, 5 items can be deleted, and the live "Black Friday launch" email uses a 1.2 MB hero image with no alt text.

| | Files | Blocks | Snippets | Email templates | SMS templates | App inbox |
|---|---|---|---|---|---|---|
| Checked | 9 | 3 | 1 | 1 | 2 | 1 |
| Live | 3 | 1 | 1 | 0 | 1 | 0 |
| Unused | 4 | 2 | 0 | not traceable | 1 not traceable | not traceable |
| Delete candidates | 3 | 2 | 0 | 0 | 0 | 0 |

### Fix (live and draft content)
| # | Priority | Item | Problem | Used by | Fix |
|---|---|---|---|---|---|
| 1 | High | archived-banner.jpg | Archived, but the live weblayer "Exit popup" still shows it | Weblayer "Exit popup" | Restore the file, or replace the image in the weblayer |
| 2 | High | hero-banner.png | 1.2 MB, 2400x1200, and shown without alt text | Email "Black Friday launch" | Resize to 1200 px wide, compress it, and add alt text |

### Images in content
| Campaign, scenario or weblayer | Status | Problem |
|---|---|---|
| Email "Black Friday launch" | Live | 1 image on http:// (http://img.cdn.example/x.png); 1 of 2 images has no alt text |
| Weblayer "Exit popup" | Live | 1 background image on http:// (http://bg.cdn.example/bg.jpg) |

### Delete candidates (verified unused)
| Item | Kind | Uploaded or edited | Why |
|---|---|---|---|
| hero-banner-final.png | File | 2026-10-15 | Duplicate of hero-banner.png (same size and dimensions); 1.2 MB; served over http:// |
| logo.d7e9962cbacf5f0d2076.png | File | 2023-07-22 | Duplicate of logo.png (same name and size); unused for 1,201 days |
| old-test-image.png | File | 2023-07-22 | Test name; unused for 1,201 days |
| Footer logo block (1) | Block | 2023-07-22 | Same name as "Footer logo block"; unused |
| Test block | Block | 2023-07-22 | Test name; unused |

### Review
| Item | Kind | State | Why |
|---|---|---|---|
| new-promo.jpg | File | Unused | Uploaded 10 days ago; someone may be about to use it |
| template-only.png | File | Template only | Used only in the "Newsletter template" email template |
| promo-draft.png | File | Draft only | 400 KB, used by the draft "Spring preview"; compress before it goes live |
| Newsletter template | Email template | Not traceable | Last edited 1,201 days ago |
| Spring sale 2023 | SMS template | Not traceable | Last edited 1,201 days ago |
| Inbox promo | App inbox template | Not traceable | Created 3 days ago |

**Not checked:** archived files (only live folders were browsed); where email, SMS and app inbox templates were copied (SMS templates matched by identical text only).
**How to act:** archive or delete in Data and Assets > Asset manager. Archive rather than delete when in doubt.
