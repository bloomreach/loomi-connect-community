# Example: quarterly business review

**This example is illustrative.** The account, names and numbers are made up; the KPI figures match the script's synthetic contract fixture.

**Prompt:** "Put together our Q3 QBR: search, categories and email, and what we should do in Q4."

## QBR: example_outdoor (Discovery) and Example Store (Engagement), 1 Jul–30 Sep 2025 vs 1 Apr–30 Jun 2025 and 1 Jul–30 Sep 2024

**Headline:** Revenue grew 20% on Q2 and 9% on last year, led by mobile and by traffic outside search and category pages. Search lost ground against last year (−3.8%) while category pages grew 21%.

| | Revenue | RPV | Conversion | AOV |
|---|---|---|---|---|
| Overall | $1.20M (+20.0% QoQ, +9.1% YoY) | $12.00 (+8.0%, +3.6%) | 5.00% (+0.22 pt, +0.16 pt) | $240 (+3.2%, +0.4%) |
| Search | $500k (+11.1%, −3.8%) | $16.67 (+3.7%, −0.6%) | 8.00% (+0.14 pt, −0.06 pt) | $208 (+1.9%, +0.2%) |
| Category | $400k (+5.3%, +21.2%) | $8.00 (+1.1%, +9.1%) | 3.60% (+0.06 pt, +0.27 pt) | $222 (−0.6%, +1.0%) |
| Other* | $300k (+76%, +20%) | — | — | — |
| Desktop / Mobile / Tablet | +16.7% / +25.0% / +25.0% revenue QoQ | $17.50 / $8.18 / $10.00 | | |
*Overall minus search and category; approximate.

### Wins
- Category pages: +$70k on last year; "Category 02" and "Category 08" rose most.
- "query 15" and "query 02" grew well ahead of overall search growth.
- Ranking test on "boots" completed: test bucket won (+6% RPV, 95% confidence).

### Problems
- query 09: revenue −82% vs Q2. Up to $16.5k this quarter → `discovery-query-diagnosis`
- query 03: conversion 0.5% vs 4.1% typical. Up to $4.9k → `discovery-query-diagnosis`
- 2 dead-end searches: 1,530 sessions, up to $4.0k → `discovery-zero-results-triage`
- Category 12: revenue −86% vs Q2. Up to $25.8k → `discovery-category-health`

### Marketing
41 email sends (2.3M delivered, 98.7% delivery, click rate 2.2%, down from 2.6% in Q2). Bounces 0.5%, unsubscribes 0.2%. Welcome and cart abandonment flows active; no browse abandonment or win-back flow.

### Experiments and work done
- 3 tests ran (2 ended, 1 still running: "Category grid test", started 1 Sep).
- Rules: 1 search ranking rule and 1 redirect created, 1 search ranking rule changed.

### Risks
- AMBER: 1 search ranking rule is still on although its end date has passed.
- AMBER: "Category grid test" is still running and locks rule changes on its categories.
- AMBER: Black Friday falls in Q4: plan and check readiness early.

### Plays for next quarter
1. **Win back search**: search is the only area down on last year (−$20k), with "query 09" and "query 03" the biggest gaps. Measure: search revenue back above Q3 2024. → `discovery-query-diagnosis`
2. **Recover Category 12**: −$25.8k on Q2. Measure: Q2 revenue restored. → `discovery-category-health`
3. **Add browse abandonment and win-back flows** before peak. Measure: flows live by mid-November. → `funnel-leak-finder`, `winback-opportunity`
4. **Plan Black Friday** and run the readiness check two weeks out. → `campaign-planner`, `peak-readiness-check`
