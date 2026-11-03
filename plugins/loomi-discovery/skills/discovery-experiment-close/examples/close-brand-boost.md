# Example: closing a brand-boost test

Prompt: "The rain jacket test looks good. Ship it."

Every name, ID and number below is invented.

---

## Close "Search terms - rain jacket" (RUNNING, 30 days, staging)

**Result:** Brand boost is 97% likely best on revenue per visit (lift +11%). Recommendation: keep Brand boost.
**Evidence check:** passed (min_confidence 95%, min_days 14, no guardrail clearly worse). Traffic split 50/50 as planned.

**What changes for shoppers of "rain jacket":** today a 50/50 split between default ranking and rule 7001 → after: rule 7001 for everyone.

**Change check (discovery-change-qa):** GO. No other enabled rule on "rain jacket"; no top seller pushed off page one.

**Steps, each needing your "yes":**
1. End the experiment keeping Brand boost. **Live at once and can't be undone**: rule 7001 serves 100% of "rain jacket" traffic; the test can't be restarted.
   `end_discovery_experiment {"account_name": "acme", "environment": "staging", "experiment_id": 900001, "winner_bucket_id": 5002}`
2. Read rule 7001 back: it should be enabled with syncStatus SUCCESS. Only if it's off: switch it on (`update_ranking_rule`, `enabled: true`; undo `enabled: false`).
3. Archive the experiment (optional). No effect on shoppers; Loomi Connect can't unarchive it.

Plan saved to `close-plan.json`. Each step is its own batch and needs its own yes.

> End "Search terms - rain jacket" now, keeping Brand boost? This is live at once and can't be undone.

*User: yes*

Ended. `close_plan.py verify` on the read-backs: the experiment is COMPLETED with Brand boost (bucket 5002) as the winner (`in_place`), and rule 7001 is enabled with syncStatus SUCCESS (`in_place`), so the conditional switch-on isn't needed.

> Archive "Search terms - rain jacket"? It has no effect on shoppers, but Loomi Connect can't unarchive it.

*User: yes*

Archived.

**Now live for "rain jacket":** rule 7001 (brand boost) for every shopper. Check in 2–4 weeks with `change-impact-tracker` that the lift held up outside the test.
