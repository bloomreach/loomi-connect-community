# Example: ad audience sync health (illustrative)

**This example is illustrative.** The method and the kinds of finding come from read-only runs against demo Engagement projects, but the project, scenario and segment names and every number have been invented.

**Prompt:** "Are our Facebook and Google audiences healthy?"

## Ad audience sync health: example-retail-prod, 4 November 2026

**Verdict:** 2 ad-audience steps and 4 external segments checked. The live "Facebook sync" step sends the "Loyal" segment without advertising consent, and two scenarios send that same segment to Facebook. Fix the consent filter first.

| Audience | Kind | Destination | Source segment | Size | Last sync | Consent | Issues |
|---|---|---|---|---|---|---|---|
| Facebook sync / Add to FB | ad step (live) | facebook-ads | Loyal | ~50 | unknown | newsletter only | no ad consent, too small, duplicate |
| Old FB sync / Push audience | ad step (inactive) | facebook-ads | Loyal | — | unknown | advertising | duplicate |
| Lapsed | external segment | — | Lapsed (archived) | — | unknown | — | source archived |
| Loyal | external segment | google | Loyal | ~250 | 20 Oct | newsletter only | failing, stale, too small, no ad consent |
| VIP buyers | external segment | — | VIP buyers | 0 | 3 Nov | advertising | empty |

### Findings
1. [High] Facebook sync / Add to FB: nothing on its path filters on the "Advertising" consent category → add the consent condition to the "Loyal" segment or the scenario before the next run.
2. [High] Lapsed: its segmentation is archived → restore it or remove the external segment.
3. [High] Loyal (external): last sync status FAILED → reconnect the sync.
4. [Medium] Two scenarios send "Loyal" to facebook-ads → keep one.
5. [Medium] Loyal (external): last synced 15 days ago, and about 250 customers, under the rule-of-thumb minimum for Google.

**Autosegments:** "Failed groups" failed on its last run; "Old groups" last ran in January and nothing uses it; "Draft groups" never ran.
**What the tools couldn't show:** no ad-platform audience list or sync history; external segments returned only id and name, except where noted; sync dates came from the user; ad steps were matched by their Facebook Ads integration ID.
**How this was checked:** 9 of 9 scenarios fetched; 3 EQL counts (cost low); no tools denied.
