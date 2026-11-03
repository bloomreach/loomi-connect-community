---
name: llm-to-script
description: Surveys loomi-connect-community skills for steps the assistant does by hand that follow fixed rules, and could be a standard-library script in the skill's scripts/ folder instead, with no loss of fidelity — sums, rates, period changes, thresholds, ranking, joins of saved tool results, pass/fail checks and table formatting. Use when a skill's answers vary between runs, its maths is error-prone, it reads very large responses, or before writing a new skill. Reports a ranked list with evidence that each script gives the same answer; writes scripts only when asked to apply.
---

You look for places in **loomi-connect-community** skills where the assistant does work a small script could do just as well: the same saved tool results in, the same numbers out, every time. The goal is answers that are right and repeatable, and fewer tokens spent reading huge responses, **without losing anything the skill gives people today**. Read `docs/skill-authoring.md` (especially **Scripts**), `docs/known-tool-behaviour.md`, and two or three skills that already use scripts well (for example `engagement-experiment-readout/scripts/ab_stats.py`, `revenue-anomaly-explainer/scripts/decompose_change.py`, `discovery-rule-audit/scripts/audit_rules.py`).

## Two modes

- **Survey (the default).** Read, measure and report. Don't change files.
- **Apply.** Only when the request says to apply, add or implement. Then, for each agreed candidate:
  - Add the script to that skill's `scripts/` folder. Standard library only, no network, no credentials, never writes next to itself (output through `--out` / `--out-dir`), JSON on stdout, a docstring with usage like the existing scripts.
  - Change the skill's steps to run it as one plain command: `python3 <skill>/scripts/<name>.py` and arguments, from the assistant's working folder. Keep (or add) the **Running the scripts** subsection.
  - **Keep the by-hand path.** Some apps run no scripts at all, so the step must still say how to do it without the script.
  - Bump `metadata.version`, run `python3 scripts/validate_skills.py`, and run the script on fixtures that show it matches (see **Proving fidelity**).

## Rules

- **Scripts only reshape data the assistant already fetched.** They never call Loomi Connect or the network. The assistant calls the tools, saves the results, and passes them to the script by path.
- **Demo data only, read-only.** When you need real response shapes or comparison runs, use a demo or sandbox project and read tools only. Never call write tools or any tool `list_all_tools` tags `internal` (listed in `docs/known-tool-behaviour.md`). Mask personal data in any fixture you keep, and never commit a real response.
- **Respect rate limits:** one Loomi Connect call at a time; EQL about 1 every 3 seconds.
- **Assistant runs cost money and time.** Run a skill end to end only to collect comparison output, at most a few runs per candidate, and say what you ran.
- **Reuse before you write.** Several skills already share scripts by copy (`grid_positions.py`, `grid_summary.py`). If an existing script does the job, copy it unchanged and say so, rather than writing a near-duplicate.

## Telling scriptable from not

**Good candidates** (the model adds nothing a function couldn't):
- arithmetic on saved results: totals, rates, points vs percent, period-over-period change, shares, medians, ranks;
- thresholds and pass/fail rules (RAG ratings, expired rules, stale catalogs, missing consent);
- joining two saved responses by key (products to categories, queries to rules, segments to `used_by`);
- pulling a few fields out of a response too big to read (product grids, event schemas, scenario designs);
- statistics with a known formula (significance, confidence intervals, test duration);
- turning a fixed set of facts into the skill's table or checklist.

**Hybrid candidates** (script the facts, keep the model for the words): the script computes every number and flag, and the assistant writes the summary, priorities and advice from its output. This usually removes most of the variance and none of the value.

**Keep with the assistant** (say why, briefly):
- understanding what the user asked, or resolving names to IDs with the user;
- judgment across many signals where the rules aren't fixed ("likely causes, ranked");
- reading images or free text (product data enhancement, synonym meaning);
- writing for people, and anything that asks follow-up questions or confirms a write;
- choices that vary by project in ways a fixed recipe would get wrong.

## Where to look

1. **Steps with numbers.** Grep `SKILL.md` and `references/` for "calculate", "compute", "percent", "change", "rate", "rank", "median", "threshold", "flag if", "count".
2. **Large responses.** Steps that tell the assistant to read a product grid, event schema, scenario design, dashboard or report definition in full.
3. **Repeated recipes.** The same calculation written out in prose in several skills.
4. **Examples.** A skill's `examples/` shows the numbers it produces; a step whose example has maths in it is a candidate.

## Proving fidelity

A script passes only if nothing is lost. For each candidate:

1. **Capture what the skill produces today:** two or three runs on demo data, or the worked numbers in its `examples/`.
2. **Run the script on the same saved inputs.**
3. **Compare item by item:** every number, flag and ranking. The script must give the same facts, or correct ones where the assistant was wrong. Explain every difference.
4. **Check the edges:** no data, a `success: false` response, a zero previous period, "NA", the response wrapper differences in `known-tool-behaviour.md`. The script must handle each one and say so in plain words.

If you can't show equivalence, report the candidate as **hybrid** or **keep**.

## Report

Start with a short summary: skills surveyed, candidates found, and your top three.

Then a ranked list, most value for least risk first. For each candidate:

- **What:** one line, in plain words.
- **Where:** `path:line` of the step in `SKILL.md` or `references/`.
- **Today:** how the assistant does it, and the evidence (runs, examples) of variance or errors.
- **Script:** what it reads, what it prints, the command the step would run, and any existing script it reuses.
- **Kind:** full script, hybrid, or keep.
- **Fidelity:** what's preserved, any difference, and how you checked (or what's still unchecked).
- **Gains:** correctness, repeatability, tokens saved.
- **Effort / Risk:** S, M or L / low, medium or high.

Then list what you'd keep with the assistant, one line each with why. When applying, finish with the scripts added, the steps changed, version bumps, validator results and the fidelity runs.
