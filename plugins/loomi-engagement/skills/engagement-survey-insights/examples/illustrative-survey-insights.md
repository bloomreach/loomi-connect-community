# Illustrative output

Prompt: "How is our post-purchase survey doing? Split the recommend score by device."

The survey, project and numbers below are invented.

---

## Survey insights: Post-purchase feedback, Example Store (production), 7 Sep to 11 Oct 2026

**Headline:** NPS-style score +25 (between +13 and +37) from 200 customers, on Engagement's 1–10 star scale; enough answers to trust the direction, but mobile and desktop customers feel very differently.

**Responses:** 200 customers answered; response rate 4.0% (3.5–4.6%) of the 5,000 customers the post-purchase email was delivered to. 30% closed the page without answering. Only 10% of those who answered the first question answered the last.

### Scores
| Question | Score | Interval | Answers | Trust |
|---|---|---|---|---|
| How likely are you to recommend us? | NPS-style +25 (1–10 stars) | +13 to +37 | 200 | OK |
| How easy was checkout? | CSAT 70% (4 or 5 of 5) | 62% to 77% | 150 | OK |

### Answers
**How did you find us?** (200 answers)
| Answer | Count | Share |
|---|---|---|
| Search | 90 | 45% |
| Friend | 40 | 20% |
| Advert | 20 | 10% |
| Other (typed in, not listed) | 50 | 25% |

**Anything else?** 60 comments (counts only).

### Trend (weekly)
| Week from | Responses | NPS-style (n) |
|---|---|---|
| 7 Sep | 20 | +50 (20, too few) |
| 14 Sep | 20 | +70 (20, too few) |
| 21 Sep | 20 | +50 (20, too few) |
| 28 Sep | 20 | +70 (20, too few) |
| 5 Oct | 5 | +20 (5, too few) |

Weekly samples are too small to compare scores; the drop in responses in the week of 5 Oct is the signal.

### Split by device
| Device | Customers | NPS-style | Interval | Note |
|---|---|---|---|---|
| mobile | 130 | +38 | +24 to +53 | |
| desktop | 65 | −8 | −30 to +15 | |
| (not set) | 5 | | | too small to compare |

The intervals don't overlap: desktop customers are clearly less likely to recommend. Device is each customer's current value, not necessarily the one they answered on.

### Flags
- **Medium:** responses fell from about 20 a week to 5 in the week of 5 Oct: check the email that carries the link, and tracking.
- **Medium:** response rate 4% of delivered emails: try a shorter survey or a later send.
- **Medium:** "What could be better?" is answered by only 10% of respondents: move it earlier or drop it.
- **Low:** 25% of "How did you find us?" answers are typed in under Other: a choice is missing.
- **Low:** the survey is active and hasn't been edited for almost three years.

**Next:** build a desktop-detractor segment for a follow-up flow with `engagement-segment-builder`; check checkout on desktop with `funnel-leak-finder`.

**How measured:** `survey` events filtered by survey ID, last 5 full weeks; 9 queries (respondents and the split `medium`, the rest `high`); the denominator is delivered `campaign` events for the post-purchase email.
