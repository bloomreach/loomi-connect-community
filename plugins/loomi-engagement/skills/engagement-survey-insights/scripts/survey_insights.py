#!/usr/bin/env python3
"""Turn saved survey definitions and aggregate EQL counts into survey insight: response rates,
answer distributions, NPS and CSAT with intervals, weekly trends, splits and flags.

Usage:
  python3 survey_insights.py --survey FILE [--respondents FILE_OR_NUMBER] [--questions FILE]
      [--answers N=FILE ...] [--shown FILE_OR_NUMBER] [--closed FILE_OR_NUMBER]
      [--trend FILE --since YYYY-MM-DD --utc-offset-minutes M [--until YYYY-MM-DD] [--trend-question N]]
      [--split-question N --split LABEL=FILE ...] [--today YYYY-MM-DD] [--rules FILE] [--out FILE]

Inputs (saved Loomi Connect results; FILE_OR_NUMBER is a number or a saved customer count,
whose rows are all added up, null rows included; an empty rows list is 0):
  --survey         search_surveys detail for one survey (questions, status, edited)
  --respondents    customers who answered any question of the survey in the window
  --questions      EQL: survey events by question_index (or by question wording)
  --answers N=FILE EQL: survey events by answer for question N (0-based position in the survey)
  --shown          customers shown or sent the survey (for the response rate), if measured
  --closed         customers who closed or dismissed it without answering, if measured
  --trend          EQL: survey events by day (timestamp ... format year month day), optionally
                   a cross-tab with answers as columns for --trend-question
  --split LABEL=FILE  EQL customer counts by a non-personal property for one answer group of
                   --split-question: promoters, passives, detractors (NPS) or satisfied,
                   unsatisfied (CSAT); any other label is counted only

NAME=VALUE inputs are split on the first "=". Free-text answers are never printed: text-field
questions, typed-in Other answers and answers to question types it doesn't know are counted only.
Prints JSON (or writes it to --out). Thresholds come from references/rules.json.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys
from fractions import Fraction
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
PRIORITY = {"high": 0, "medium": 1, "low": 2}
URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s'\"<>]+")
CHOICE_TYPES = {"single-choice", "multiple-choice", "multiple-choices", "multi-choice"}
TEXT_TYPES = {"textfield", "text-field", "textarea", "text"}
RATING_TYPES = {"rating-stars", "rating"}
NPS_LABELS = ("promoters", "passives", "detractors")
CSAT_LABELS = ("satisfied", "unsatisfied")
HANDOFFS = {
    "too_few_responses": "onsite-experience-audit",
    "stale_active": "onsite-experience-audit",
    "not_edited_recently": "onsite-experience-audit",
    "skipped_question": "onsite-experience-audit",
    "low_response_rate": "onsite-experience-audit",
    "response_drop": "engagement-tracking-health",
    "detractors_outnumber_promoters": "engagement-segment-builder",
    "low_satisfaction": "engagement-segment-builder",
    "other_answers_common": "onsite-experience-audit",
}


def fail(msg):
    print(json.dumps({"ok": False, "error": redact(msg)}))
    sys.exit(1)


def redact(text):
    return URL.sub("[url]", str(text))


def number(v):
    """A number from a tool value ("$1,000.00", "2.50%", "(12.00)"), or None when missing or not a number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.lower() in MISSING:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s[:1] in ("−", "–"):
        s = "-" + s[1:]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    s = re.sub(r"[$£€,%\s]", "", s)
    m = re.match(r"[+]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    if not m:
        return None
    x = float(m.group(0))
    if not math.isfinite(x):
        return None
    return -x if negative else x


def load_rules(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"{path}: can't read the rules file ({e.strerror or e}).")
    except json.JSONDecodeError as e:
        fail(f"{path}: the rules file isn't valid JSON ({e}).")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        fail(f"{path}: can't read the file ({e.strerror or e}).")
    except json.JSONDecodeError as e:
        fail(f"{path}: not valid JSON ({e}).")
    for _ in range(3):
        if isinstance(data, dict) and isinstance(data.get("result"), dict) and len(data) == 1:
            data = data["result"]
        if isinstance(data, dict) and data.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {data.get('error') or 'no error text'}. "
                 "This input couldn't be read; don't treat it as 'nothing found'.")
        if isinstance(data, dict) and "success" in data and "data" in data and not isinstance(data.get("rows"), list):
            data = data["data"]
    return data


def report(data, path):
    """The report body of an EQL result: a dict with rows (and columns for a cross-tab)."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        fail(f"{path}: no EQL rows found; save the execute_analytics_eql result.")
    if data.get("valid") is False:
        fail(f"{path}: the EQL report came back with valid: false (too many rows). Narrow the window or use grouping top N.")
    return data


def pair(text):
    """NAME=VALUE, split on the first "="."""
    name, sep, value = text.partition("=")
    if not sep or not name.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=FILE, got {text!r}")
    return name.strip(), value.strip()


def first_header(row):
    heads = row.get("headers") or []
    if not heads:
        return None
    h = heads[0]
    return h.get("value") if isinstance(h, dict) else h


def rows_of(path):
    """[(header value, [values])] from an EQL breakdown."""
    rep = report(load(path), path)
    out = []
    for r in rep["rows"]:
        if isinstance(r, dict):
            out.append((first_header(r), [number(v) or 0.0 for v in (r.get("values") or [])]))
    cols = []
    for c in rep.get("columns") or []:
        if isinstance(c, list) and c:
            h = c[0]
            cols.append(h.get("value") if isinstance(h, dict) else h)
        elif isinstance(c, list):
            cols.append(None)
    return out, cols


def count_of(value, label):
    if value is None:
        return None
    if os.path.exists(value):
        rows, _ = rows_of(value)
        return sum(sum(vals) for _, vals in rows)
    x = number(value)
    if x is None or x < 0:
        fail(f"{label}: {value!r} is neither a file nor a count.")
    return x


def z_value(confidence):
    if not 0 < confidence < 1:
        fail("confidence in the rules must be between 0 and 1.")
    return statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)


def wilson(k, n, z):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def ratio(k, n):
    return None if not n else round(k / n, 4)


def sample_label(n, rules):
    if n < rules["min_responses"]:
        return "too_few"
    if n < rules["small_sample"]:
        return "small"
    return "ok"


def sample_note(n, rules):
    lab = sample_label(n, rules)
    if lab == "too_few":
        return f"Only {int(n)} answers: too few to trust; don't act on this score."
    if lab == "small":
        return f"{int(n)} answers: a small sample, so the interval is wide; treat the score as a rough guide."
    return None


def nps_score(promoters, passives, detractors, rules, z):
    n = promoters + passives + detractors
    if not n:
        return None
    p, d = promoters / n, detractors / n
    score = (Fraction(int(promoters)) - Fraction(int(detractors))) * 100 / Fraction(int(n))
    se = math.sqrt(max(p + d - (p - d) ** 2, 0.0) / n) * 100
    v = float(score)
    return {"kind": "nps", "score": round(v, 1), "interval": [round(max(-100.0, v - z * se), 1), round(min(100.0, v + z * se), 1)],
            "n": int(n), "promoters": int(promoters), "passives": int(passives), "detractors": int(detractors),
            "sample": sample_label(n, rules), "note": sample_note(n, rules)}


def csat_score(satisfied, n, rules, z):
    if not n:
        return None
    return {"kind": "csat", "score": ratio(satisfied, n), "interval": wilson(satisfied, n, z), "n": int(n),
            "satisfied": int(satisfied), "sample": sample_label(n, rules), "note": sample_note(n, rules)}


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def survey_body(data, path):
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        fail(f"{path}: no questions found; save search_surveys called with survey_id (the detail, not the list).")
    return data


def question_kind(q, rules):
    t = str(q.get("type") or "").lower()
    data = q.get("data") if isinstance(q.get("data"), dict) else {}
    if t in RATING_TYPES:
        stars = number(data.get("number_of_stars"))
        stars = int(stars) if stars else None
        if stars in rules["nps_star_counts"]:
            return "nps", stars
        if stars is not None and str(stars) in rules["csat_top_box"]:
            return "csat", stars
        return "rating", stars
    if t in CHOICE_TYPES:
        return "choice", None
    if t in TEXT_TYPES:
        return "free_text", None
    if t == "matrix":
        return "matrix", None
    return "unknown", None


def choices_of(q):
    data = q.get("data") if isinstance(q.get("data"), dict) else {}
    out = []
    for c in data.get("choices") or []:
        name = c.get("name") if isinstance(c, dict) else c
        if isinstance(name, str) and name.strip():
            out.append(name)
    return out, bool(data.get("other"))


def answer_items(value, choices):
    """The answers in one header value: a list's items, a choice, or a comma-joined list of choices."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return [None]
    s = str(value)
    if s in choices or not choices:
        return [s]
    parts = [p.strip() for p in s.split(",")]
    if len(parts) > 1 and all(p in choices for p in parts):
        return parts
    return [s]


def distribution(q, kind, stars, path, rules, z):
    """Answer counts and score for one question, never echoing free text."""
    rows, _ = rows_of(path)
    total = sum(sum(v) for _, v in rows)
    out = {"answers_counted": int(total)}
    if kind in ("free_text", "matrix", "unknown"):
        out["distinct_values_in_result"] = len(rows)
        out["values_listed"] = False
        out["why"] = {"free_text": "free-text answers are counted only, never listed",
                      "matrix": "matrix answers need a breakdown by sub_question_index; counted only",
                      "unknown": "question type not recognised, so its answers may be free text; counted only"}[kind]
        return out, None
    counts, other, unreadable = {}, 0.0, 0.0
    choices, _ = choices_of(q) if kind == "choice" else ([], False)
    for value, vals in rows:
        c = sum(vals)
        if kind == "choice":
            for item in answer_items(value, choices):
                if item in choices:
                    counts[item] = counts.get(item, 0.0) + c
                else:
                    other += c
        else:
            x = number(value) if not isinstance(value, bool) else None
            if x is None or x != int(x) or x < 0 or (stars and x > stars):
                unreadable += c
            else:
                counts[int(x)] = counts.get(int(x), 0.0) + c
    multi = kind == "choice" and "multi" in str(q.get("type") or "").lower()
    # A multiple-choice response can hold several answers, so its shares are of responses, not of answers.
    answered = total if multi else sum(counts.values()) + other
    if kind == "choice":
        keys = sorted(counts, key=lambda k: (choices.index(k), k))
        keys += [k for k in choices if k not in counts]
    else:
        lo = 0 if counts and min(counts) == 0 else 1
        hi = stars or (max(counts) if counts else 0)
        keys = list(range(lo, hi + 1))
    cap = rules["max_answer_values"]
    listed = keys[:cap]
    rest = sum(counts.get(k, 0.0) for k in keys[cap:])
    out["distribution"] = [{"answer": k, "count": int(counts.get(k, 0.0)), "share": ratio(counts.get(k, 0.0), answered),
                            "interval": wilson(counts.get(k, 0.0), answered, z)} for k in listed]
    if rest:
        out["rest"] = {"count": int(rest), "share": ratio(rest, answered)}
    if kind == "choice":
        out["other_typed_in"] = {"count": int(other), "share": ratio(other, answered), "values_listed": False}
        if multi:
            out["note"] = "Several answers per response are possible, so shares can add up to more than 100%."
    if unreadable:
        out["unreadable"] = int(unreadable)
    score = None
    if kind == "nps":
        pro = sum(v for k, v in counts.items() if k >= rules["nps_promoter_min"])
        pas = sum(v for k, v in counts.items() if rules["nps_passive_min"] <= k < rules["nps_promoter_min"])
        det = sum(v for k, v in counts.items() if k < rules["nps_passive_min"])
        score = nps_score(pro, pas, det, rules, z)
        if score:
            lo = 0 if 0 in counts else 1
            score["scale"] = f"{lo} to {stars}"
            if lo == 1:
                score["label"] = (f"NPS-style score on a 1 to {stars} star scale (not the standard 0 to 10): "
                                  f"promoters {rules['nps_promoter_min']}+, detractors below {rules['nps_passive_min']}")
            else:
                score["label"] = "Net Promoter Score (0 to 10)"
    elif kind == "csat":
        top = int(rules["csat_top_box"][str(stars)])
        n = sum(counts.values())
        sat = sum(v for k, v in counts.items() if k > stars - top)
        score = csat_score(sat, n, rules, z)
        if score:
            score["label"] = f"CSAT: share answering {stars - top + 1} or more out of {stars}"
    if kind in ("nps", "csat", "rating"):
        n = sum(counts.values())
        if n:
            mean = sum(Fraction(int(k)) * Fraction(int(v)) for k, v in counts.items()) / Fraction(int(n))
            out["average"] = round(float(mean), 2)
    return out, score


def bucket_date(raw, offset_minutes):
    if isinstance(raw, str) and re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        try:
            return datetime.date.fromisoformat(raw[:10])
        except ValueError:
            return None
    x = number(raw)
    if x is None or x < 10**8:
        return None
    # Buckets start at local midnight. Adding the offset and rounding to the nearest midnight
    # absorbs a daylight-saving hour either way.
    day = math.floor((x + offset_minutes * 60 + 43200) / 86400)
    return datetime.date(1970, 1, 1) + datetime.timedelta(days=day)


def weekly(a, rules, z, kinds, today):
    if not a.since or a.utc_offset_minutes is None:
        fail("--trend needs --since (the window's first day, in the project's time zone) and --utc-offset-minutes "
             "(read it from the buckets: a bucket at 23:00 UTC is local midnight in a UTC+1 project, so 60).")
    try:
        since = datetime.date.fromisoformat(a.since)
        until = datetime.date.fromisoformat(a.until) if a.until else today
    except ValueError:
        fail("--since and --until must be dates as YYYY-MM-DD.")
    if until < since:
        fail("--until is before --since.")
    rows, cols = rows_of(a.trend)
    kind = stars = None
    if a.trend_question is not None:
        kind, stars = kinds.get(a.trend_question, (None, None))
        if kind not in ("nps", "csat"):
            fail(f"--trend-question {a.trend_question} isn't an NPS or CSAT question in this survey.")
    weeks, outside = {}, 0.0
    for raw, vals in rows:
        d = bucket_date(raw, a.utc_offset_minutes)
        if d is None or d < since or d > until:
            outside += sum(vals)
            continue
        w = (d - since).days // 7
        wk = weeks.setdefault(w, {"responses": 0.0, "answers": {}})
        wk["responses"] += sum(vals)
        if kind and cols:
            for i, v in enumerate(vals):
                ans = number(cols[i]) if i < len(cols) else None
                if ans is not None and ans == int(ans):
                    wk["answers"][int(ans)] = wk["answers"].get(int(ans), 0.0) + v
    n_weeks = (until - since).days // 7 + 1
    out = []
    for w in range(n_weeks):
        start = since + datetime.timedelta(days=7 * w)
        end = min(start + datetime.timedelta(days=6), until)
        wk = weeks.get(w, {"responses": 0.0, "answers": {}})
        row = {"week_start": start.isoformat(), "week_end": end.isoformat(), "full_week": (end - start).days == 6,
               "responses": int(wk["responses"])}
        if kind == "nps":
            ans = wk["answers"]
            s = nps_score(sum(v for k, v in ans.items() if k >= rules["nps_promoter_min"]),
                          sum(v for k, v in ans.items() if rules["nps_passive_min"] <= k < rules["nps_promoter_min"]),
                          sum(v for k, v in ans.items() if k < rules["nps_passive_min"]), rules, z)
            row["nps"] = None if not s else {"score": s["score"], "interval": s["interval"], "n": s["n"], "sample": s["sample"]}
        elif kind == "csat":
            ans = wk["answers"]
            top = int(rules["csat_top_box"][str(stars)])
            n = sum(ans.values())
            s = csat_score(sum(v for k, v in ans.items() if k > stars - top), n, rules, z)
            row["csat"] = None if not s else {"score": s["score"], "interval": s["interval"], "n": s["n"], "sample": s["sample"]}
        out.append(row)
    return {"since": since.isoformat(), "until": until.isoformat(), "utc_offset_minutes": a.utc_offset_minutes,
            "question": a.trend_question, "weeks": out, "outside_window": int(outside)}


def splits(a, rules, z, kinds):
    if a.split_question is None:
        fail("--split needs --split-question (the question the groups come from).")
    kind, _ = kinds.get(a.split_question, (None, None))
    labels = [lab.lower() for lab, _ in a.split]
    if len(set(labels)) != len(labels):
        fail("each --split label can be given once.")
    data = {}
    for lab, path in a.split:
        rows, _ = rows_of(path)
        for raw, vals in rows:
            key = "(not set)" if raw is None or raw == "" else str(raw)
            data.setdefault(key, {})
            data[key][lab.lower()] = data[key].get(lab.lower(), 0.0) + sum(vals)
    mode = "nps" if set(labels) == set(NPS_LABELS) else "csat" if set(labels) == set(CSAT_LABELS) else "counts"
    if mode == "nps" and kind != "nps":
        fail(f"--split-question {a.split_question} isn't an NPS-style question, but the split labels are promoters, passives and detractors.")
    if mode == "csat" and kind != "csat":
        fail(f"--split-question {a.split_question} isn't a CSAT question, but the split labels are satisfied and unsatisfied.")
    groups = []
    for key in sorted(data):
        g = data[key]
        n = sum(g.values())
        row = {"value": key, "customers": int(n), "counts": {k: int(g.get(k, 0.0)) for k in sorted(set(labels))},
               "too_small": n < rules["min_split_group"]}
        if mode == "nps":
            s = nps_score(g.get("promoters", 0.0), g.get("passives", 0.0), g.get("detractors", 0.0), rules, z)
            row["nps"] = None if not s else {"score": s["score"], "interval": s["interval"]}
        elif mode == "csat":
            s = csat_score(g.get("satisfied", 0.0), n, rules, z)
            row["csat"] = None if not s else {"score": s["score"], "interval": s["interval"]}
        groups.append(row)
    groups.sort(key=lambda r: (-r["customers"], r["value"]))
    return {"question": a.split_question, "mode": mode, "groups": groups,
            "note": "Customer counts: a customer whose answers fall in two groups (a recurrent survey) counts in both."}


def build(a, rules):
    z = z_value(rules["confidence"])
    try:
        today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    except ValueError:
        fail("--today must be a date as YYYY-MM-DD.")
    survey = survey_body(load(a.survey), a.survey)
    questions = [q for q in survey["questions"] if isinstance(q, dict)]
    kinds = {i: question_kind(q, rules) for i, q in enumerate(questions)}
    findings = []

    def add(priority, kind, text, **extra):
        f = {"priority": priority, "kind": kind, "finding": text, **extra}
        if kind in HANDOFFS:
            f["hand_off"] = HANDOFFS[kind]
        findings.append(f)

    respondents = count_of(a.respondents, "--respondents")
    shown = count_of(a.shown, "--shown")
    closed = count_of(a.closed, "--closed")

    q_counts, unmatched = {}, 0.0
    if a.questions:
        rows, _ = rows_of(a.questions)
        by_text = {norm(q.get("name")): i for i, q in enumerate(questions)}
        for raw, vals in rows:
            x = number(raw) if not isinstance(raw, str) or re.match(r"^\s*\d+\s*$", raw) else None
            if x is not None and x == int(x) and 0 <= x < len(questions):
                i = int(x)
            else:
                i = by_text.get(norm(raw))
            if i is None:
                unmatched += sum(vals)
            else:
                q_counts[i] = q_counts.get(i, 0.0) + sum(vals)

    answers = {}
    for name, path in a.answers:
        x = number(name)
        if x is None or x != int(x) or not 0 <= x < len(questions):
            fail(f"--answers {name}=...: {name!r} isn't a question position in this survey (0 to {len(questions) - 1}).")
        answers[int(x)] = path

    base = respondents if respondents else (max(q_counts.values()) if q_counts else None)
    base_kind = "respondents" if respondents else ("most_answered_question" if q_counts else None)
    out_q, scores = [], {}
    for i, q in enumerate(questions):
        kind, stars = kinds[i]
        row = {"index": i, "question": q.get("name"), "type": q.get("type"), "kind": kind, "mandatory": bool(q.get("mandatory"))}
        if stars:
            row["stars"] = stars
        if i in q_counts:
            row["answered"] = int(q_counts[i])
            row["answered_share"] = ratio(q_counts[i], base) if base else None
        if i in answers:
            dist, score = distribution(q, kind, stars, answers[i], rules, z)
            row.update(dist)
            if score:
                row["score"] = score
                scores[i] = score
        out_q.append(row)

    name = survey.get("name")
    status = str(survey.get("status") or "").lower()
    response = {"respondents": None if respondents is None else int(respondents), "shown": None if shown is None else int(shown),
                "closed": None if closed is None else int(closed)}
    if shown:
        if respondents is not None:
            response["response_rate"] = ratio(respondents, shown)
            response["response_rate_interval"] = wilson(respondents, shown, z)
        if closed is not None:
            response["close_rate"] = ratio(closed, shown)
            response["close_rate_interval"] = wilson(closed, shown, z)
    if q_counts and respondents and max(q_counts.values()) > respondents:
        response["note"] = ("Some questions have more answers than respondents: the survey is probably recurrent, or customers "
                            "answered more than once in the window. Rates use customers.")
    if q_counts and len(questions) > 1 and q_counts.get(0):
        last = len(questions) - 1
        response["last_question_vs_first"] = ratio(q_counts.get(last, 0.0), q_counts[0])
    if unmatched:
        response["unmatched_question_events"] = int(unmatched)

    # Flags
    if respondents is not None:
        if status == "active" and respondents == 0:
            add("high", "stale_active", "Active, but nobody answered in the window: check the link, the campaign or weblayer that "
                "carries it, and tracking, or switch it off.")
        elif respondents < rules["min_responses"]:
            add("high", "too_few_responses", f"Only {int(respondents)} respondents in the window: too few to trust any score. "
                "Widen the window or get the survey in front of more people before acting on it.")
    edited = number(survey.get("edited"))
    if status == "active" and edited:
        age = (today - datetime.datetime.fromtimestamp(edited, datetime.timezone.utc).date()).days
        if age >= rules["stale_edit_days"]:
            add("low", "not_edited_recently", f"Active and not edited for {age} days: check it still asks the right questions.", days=age)
    if shown and respondents is not None and respondents / shown < rules["low_response_rate"]:
        add("medium", "low_response_rate", "Few of the people shown or sent the survey answered it: shorten it, move it, or "
            "reconsider the timing.", response_rate=ratio(respondents, shown))
    if base:
        for i, q in enumerate(questions):
            if i in q_counts and q_counts[i] / base < rules["skip_flag_share"]:
                mand = bool(q.get("mandatory"))
                add("high" if mand else "medium", "skipped_question",
                    ("Mandatory, yet most respondents have no answer: check tracking and the question's position (is it after a branch?)."
                     if mand else "Most respondents skip this question: drop it, move it earlier, or make it easier to answer."),
                    question=i, answered_share=ratio(q_counts[i], base))
        if a.questions:
            for i in range(len(questions)):
                if i not in q_counts:
                    add("medium", "skipped_question", "No answers at all to this question in the window.", question=i, answered_share=0.0)
    for i, s in sorted(scores.items()):
        if s["kind"] == "nps" and s["detractors"] > s["promoters"] and s["sample"] != "too_few":
            add("medium", "detractors_outnumber_promoters", "Detractors outnumber promoters: worth a follow-up flow for detractors.",
                question=i, score=s["score"])
        if s["kind"] == "csat" and s["sample"] != "too_few" and s["interval"] and s["interval"][1] < 0.5:
            add("medium", "low_satisfaction", "Fewer than half are satisfied, even at the top of the interval.", question=i, score=s["score"])
    for row in out_q:
        o = row.get("other_typed_in")
        if o and o["share"] is not None and o["share"] >= rules["other_flag_share"] and o["count"]:
            add("low", "other_answers_common", "Many answers are typed in under Other: a choice is probably missing. "
                "Their text is not listed here.", question=row["index"], other_share=o["share"])
        if row["kind"] == "free_text" and row.get("answers_counted"):
            add("low", "free_text_counts_only", "Free-text answers counted only. Themes only on request, from a small capped sample.",
                question=row["index"])

    result = {"ok": True, "as_of": today.isoformat(),
              "survey": {"name": name, "status": status or None, "archived": bool(survey.get("archived")),
                         "questions": len(questions), "edited": (datetime.datetime.fromtimestamp(edited, datetime.timezone.utc).date().isoformat()
                                                                if edited else None)},
              "response": response, "answered_share_base": base_kind, "questions": out_q}
    if a.trend:
        t = weekly(a, rules, z, kinds, today)
        result["trend"] = t
        full = [w for w in t["weeks"] if w["full_week"]]
        if len(full) >= 3:
            earlier = statistics.median(w["responses"] for w in full[:-1])
            latest = full[-1]["responses"]
            if earlier >= rules["trend_min_weekly"] and latest < rules["trend_drop_share"] * earlier:
                add("medium", "response_drop", "Responses in the latest full week fell well below the weeks before: check the "
                    "survey link, the campaign or weblayer carrying it, and tracking.", week_start=full[-1]["week_start"],
                    latest=latest, earlier_median=earlier)
    if a.split:
        result["split"] = splits(a, rules, z, kinds)
    findings.sort(key=lambda f: (PRIORITY[f["priority"]], f["kind"], f.get("question", -1)))
    result["findings"] = findings
    result["summary"] = {"respondents": response["respondents"], "scores": {str(i): {"kind": s["kind"], "score": s["score"], "n": s["n"]}
                                                                          for i, s in sorted(scores.items())},
                         "findings": {p: sum(1 for f in findings if f["priority"] == p) for p in ("high", "medium", "low")}}
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # survey and question names can hold any character
    rules_default = str(RULES_PATH)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--survey", required=True, help="saved search_surveys detail for one survey (called with survey_id)")
    ap.add_argument("--respondents", help="customers who answered any question in the window: a number or a saved EQL count")
    ap.add_argument("--questions", help="saved EQL: survey events by question_index (or by question wording)")
    ap.add_argument("--answers", action="append", type=pair, default=[], help="N=FILE: saved EQL of survey events by answer for question N (0-based); repeat")
    ap.add_argument("--shown", help="customers shown or sent the survey: a number or a saved EQL count (optional)")
    ap.add_argument("--closed", help="customers who closed it without answering: a number or a saved EQL count (optional)")
    ap.add_argument("--trend", help="saved EQL: survey events by day, or a day-by-answer cross-tab for --trend-question")
    ap.add_argument("--trend-question", type=int, help="question position whose answers are the --trend columns (NPS or CSAT)")
    ap.add_argument("--since", help="first day of the trend window, YYYY-MM-DD in the project's time zone")
    ap.add_argument("--until", help="last day of the trend window, YYYY-MM-DD (default: --today)")
    ap.add_argument("--utc-offset-minutes", type=int, help="the project's UTC offset in minutes, read from the day buckets (UTC+1 is 60)")
    ap.add_argument("--split-question", type=int, help="question position the --split groups come from")
    ap.add_argument("--split", action="append", type=pair, default=[], help="LABEL=FILE: customers by a non-personal property for one answer group; repeat")
    ap.add_argument("--today", help="today's date as YYYY-MM-DD (default: the system date)")
    ap.add_argument("--rules", default=rules_default, help="rules file (default: this skill's references/rules.json)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()

    rules = load_rules(a.rules)
    result = build(a, rules)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write the file ({e.strerror or e}).")
        print(json.dumps({"ok": True, "out": a.out, "summary": result["summary"]}, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
