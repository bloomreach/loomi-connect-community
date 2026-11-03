# Example: 13-week trend (illustrative)

**This example is illustrative.** The project, campaign names, domains and all figures are invented to show the output format. They do not come from a real project.

**Prompt:** "Spam complaints feel high lately. Is our deliverability getting worse?"

## Email deliverability trend: example_retail_prod, 5 Aug to 2 Nov 2026 (14 weeks, sends = enqueued)

**Headline:** Complaints have risen from about 0.05% to 0.27% over the last three weeks and passed the 0.3% rule-of-thumb limit in the week of 26 Oct; bounces and delivery are steady apart from one September spike.

| Week of | Sends | Delivery % | Hard bounce % | Soft bounce % | Complaint % | Unsub % | Note |
|---|---|---|---|---|---|---|---|
| 3 Aug | 5,000 | 98.7 | 0.3 | 1.0 | 0.041 | 0.3 | partial |
| ... | | | | | | | |
| 14 Sep | 7,000 | 97.9 | 1.1 | 1.0 | 0.058 | 0.3 | hard bounce spike |
| ... | | | | | | | |
| 12 Oct | 7,000 | 98.7 | 0.3 | 1.0 | 0.203 | 0.3 | |
| 19 Oct | 7,000 | 98.7 | 0.3 | 1.0 | 0.203 | 0.3 | |
| 26 Oct | 7,000 | 98.7 | 0.3 | 1.0 | 0.405 | 0.3 | over 0.3% |
| 2 Nov | 500 | 98.7 | 0.2 | 1.0 | 0.405 | 0.3 | partial, low volume |
| **Baseline** (10 weeks) | | 98.6 | 0.4 | 1.0 | 0.049 | 0.3 | |
| **Recent** (3 weeks) | | 98.7 | 0.3 | 1.0 | 0.270 | 0.3 | |

### Findings (high first)
1. **High** Complaint rate over the 0.3% limit in the week of 26 Oct (0.405%), and 0.27% over the last three weeks. Check: which broadcast went out that week (see below), and the domain's spam rate in Gmail Postmaster Tools.
2. **Medium** Complaint rate drift: 0.049% baseline to 0.27% recent, against the project's own history.
3. **Medium** One-off campaigns: hard bounce 2.8%, complaint 0.37% over the window, against 0.28% and 0.04% for scenarios. Likely cause: broadcast audiences, not automated flows.
4. **Medium** New recipients (no email before the window): hard bounce 2.4%. Likely cause: an imported list. Check its source and suppress hard bounces.
5. **Low** Hard bounce spike in the week of 14 Sep (1.1%, 78 bounces), since recovered: Autumn sale had 64% of that week's problem events.

### Where it comes from
- **Sending domain:** shop.example 0.27% hard bounce, 0.072% complaints (70,000 sends); mail.example 2.5% hard bounce (10,000 sends).
- **Scenarios vs one-off campaigns:** above.
- **New vs established recipients:** new 2.4% hard bounce, established 0.1%.
- **Spike weeks:** 14 Sep: Autumn sale (64% of problem events), Newsletter (36%).

**Guard-rails used:** complaint 0.1% warn / 0.3% limit (bulk-sender guidance); hard bounce 1% / 2%; soft bounce 3% / 5%; unsubscribe 0.5% / 1%; delivery below 98% / 95%. Rules of thumb, not provider limits.
**Coverage notes:** 6 EQL queries, all `high`. Integration breakdown skipped (one integration).
