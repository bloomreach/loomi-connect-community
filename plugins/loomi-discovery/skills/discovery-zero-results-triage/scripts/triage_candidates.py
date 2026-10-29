#!/usr/bin/env python3
"""Suggest a likely fix for each dead-end search, from saved Loomi Connect output, before the product grid checks.

Usage:
  python3 triage_candidates.py --no-results nr.json --no-revenue nv.json --top top.json \
      [--synonyms syn.json] [--redirects red.json] [--min-sessions N] [--out triage.json]

Inputs are the raw JSON responses (or files the client saved them to); a comma-separated list
of files reads several pages of one call:
  --no-results  get_discovery_query_performance with filter_preset="no_search_results"
  --no-revenue  get_discovery_query_performance with filter_preset="no_revenue"
  --top         get_discovery_query_performance with sort="browse_sessions" (the selling searches)
  --synonyms    list_synonyms_user        (optional)
  --redirects   search_redirects          (optional)

Prints JSON (or writes it to --out) with each dead-end search, busiest revenue at stake first:
  kind:      no_results (the no_search_results list, or a no_revenue row with no product views)
             or no_sales (product views but no revenue);
  class:     a suggestion only, the first that fits of
             noise                 too few sessions, under 2 letters or digits only;
             covered_by_redirect   an enabled redirect already lists it;
             page_intent           a no-results search for a page (returns, store hours);
             spelling_twin         a misspelling or variant of a selling search (`twin`);
             synonym_no_results    has a synonym to another word and still finds nothing;
             noop_synonym          its only synonyms point back at itself;
             none                  nothing above (no_sales: check ranking; no_results: try wordings);
  revenue_at_stake: sessions x the typical revenue per search session (median of the busiest
             top searches' revenue / sessions).
The thresholds and page-intent words come from references/rules.json.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

# The rules live in references/rules.json, shared with apps that suggest the same fixes.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}


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


def num(v):
    x = number(v)
    return 0.0 if x is None else x


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            print(json.dumps({"ok": False, "error": f"{path}: Loomi Connect returned an error: "
                              f"{d.get('error') or d.get('message') or 'no error text'}. This check couldn't run; "
                              "don't treat it as 'nothing found'."}))
            sys.exit(1)
    if isinstance(data, dict) and isinstance(data.get("result"), dict) and len(data) == 1:
        data = data["result"]
    if isinstance(data, dict) and "success" in data and "data" in data:
        data = data["data"]
    return data


def rows_of(data):
    """The objects in a list answer: a bare list, {"rows": [...]} or {"data": [...]}."""
    if isinstance(data, dict):
        data = data.get("rows") if isinstance(data.get("rows"), list) else data.get("data")
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def read_rows(paths):
    out = []
    for p in (paths or "").split(","):
        if p:
            out.extend(rows_of(load(p)))
    return out


def metric(r):
    name = r.get("query") if r.get("query") is not None else r.get("name")
    sessions = r.get("browse_sessions") if r.get("browse_sessions") is not None else r.get("visits")
    prev = r.get("prev_browse_sessions") if r.get("prev_browse_sessions") is not None else r.get("prev_visits")
    return {"query": "—" if name is None else str(name), "sessions": num(sessions), "prev_sessions": num(prev),
            "views": num(r.get("product_page_views")), "revenue": num(r.get("revenue"))}


def median(xs):
    s = sorted(x for x in xs if math.isfinite(x))
    if not s:
        return 0.0
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def squash(q):
    return re.sub(r"[^a-z0-9]", "", q.lower())


def distance(a, b, cap):
    """Edit distance, capped: anything over `cap` is cap + 1."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i]
        for j in range(1, len(b) + 1):
            row.append(min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (0 if a[i - 1] == b[j - 1] else 1)))
        if min(row) > cap:
            return cap + 1
        prev = row
    return prev[len(b)]


def twin_of(query, sellers, rules):
    """The first selling search this one is a misspelling or variant of ("tshirt" -> "t shirt"), or None."""
    q = squash(query)
    if len(q) < rules["lookalike_min_chars"]:
        return None
    cap = rules["max_edits_long"] if len(q) >= rules["long_query_chars"] else rules["max_edits_short"]
    for s in sellers:
        other = squash(s["query"])
        if s["query"] != query and (other == q or distance(q, other, cap) <= cap):
            return s
    return None


def page_intent(rules):
    words = sorted(rules["page_intent_words"], key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE | re.ASCII)


def synonym_map(rows):
    """Each enabled synonym's source -> whether any target differs from it ("corset -> corset" does nothing)."""
    out = {}
    for s in rows:
        if s.get("enabled") is False:
            continue
        source = str(s.get("sourceSynonym") or "").strip().lower()
        targets = [t.strip().lower() for t in str(s.get("targetSynonym") or "").split(",")]
        out[source] = out.get(source, False) or any(t and t != source for t in targets)
    return out


def redirect_set(rows):
    return {str(q.get("query") or "").lower() for r in rows if r.get("enabled") is not False
            for q in rows_of(r.get("queries"))}


REASONS = {
    "noise": "Too few sessions, or not a real word, to be worth fixing.",
    "covered_by_redirect": "An enabled redirect already lists this search. Check the page it goes to still exists.",
    "page_intent": "Shoppers want a page, not products. A redirect fits better than results.",
    "spelling_twin": "Looks like another way of writing a search that sells. A synonym to it would probably show results.",
    "synonym_no_results": "It already has a synonym to another word and still finds nothing: likely a catalog gap.",
    "noop_synonym": "Its only synonym points back to itself, so it does nothing.",
    "none": "No suggestion from the data alone.",
}


def classify(q, kind, sellers, synonyms, redirects, rules, intent):
    """The first class that fits, and the twin for spelling_twin. Same order as the app's dead-ends page."""
    name = q["query"].lower()
    s = squash(q["query"])
    if q["sessions"] < rules["min_sessions"] or len(s) < rules["min_query_chars"] or s.isdigit():
        return "noise", None
    if name in redirects:
        return "covered_by_redirect", None
    if kind == "no_results" and intent.search(name):
        return "page_intent", None
    twin = twin_of(q["query"], sellers, rules)
    if twin:
        return "spelling_twin", twin
    if kind == "no_sales":
        return "none", None
    if synonyms.get(name):
        return "synonym_no_results", None
    if name in synonyms:
        return "noop_synonym", None
    return "none", None


def triage(no_results, no_revenue, top, synonym_rows, redirect_rows, rules):
    intent = page_intent(rules)
    synonyms, redirects = synonym_map(synonym_rows), redirect_set(redirect_rows)
    sellers = [t for t in top if t["revenue"] > 0]
    peers = sorted(top, key=lambda t: -t["sessions"])[:rules["peers"]]
    rpv = median([p["revenue"] / p["sessions"] if p["sessions"] else 0.0 for p in peers])
    zero = {q["query"] for q in no_results}
    # A no_revenue row nobody viewed a product from is a dead end too: the no_search_results preset misses most.
    listed = [(q, "no_results") for q in no_results] + [
        (q, "no_results" if q["views"] == 0 and q["sessions"] > 0 else "no_sales")
        for q in no_revenue if q["query"] not in zero]
    out = []
    for q, kind in listed:
        cls, twin = classify(q, kind, sellers, synonyms, redirects, rules, intent)
        row = {"query": q["query"], "kind": kind, "sessions": int(q["sessions"]), "prev_sessions": int(q["prev_sessions"]),
               "class": cls, "reason": REASONS[cls], "revenue_at_stake": round(q["sessions"] * rpv, 2)}
        if twin:
            row["twin"] = {"query": twin["query"], "sessions": int(twin["sessions"]), "revenue": round(twin["revenue"], 2)}
        out.append(row)
    out.sort(key=lambda r: -r["revenue_at_stake"])
    counts = {}
    for r in out:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    real = [r for r in out if r["class"] != "noise"]
    return {
        "ok": True,
        "note": "Suggestions only. Confirm each one with the product grid before recommending a fix.",
        "typical_revenue_per_session": round(rpv, 4),
        "summary": {
            "dead_ends": len(out),
            "by_class": dict(sorted(counts.items())),
            "sessions": int(sum(r["sessions"] for r in real)),
            "revenue_at_stake": round(sum(r["revenue_at_stake"] for r in real), 2),
            "noise_sessions": int(sum(r["sessions"] for r in out if r["class"] == "noise")),
        },
        "queries": out,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-results", required=True, help="saved no_search_results query performance (comma-separated pages)")
    ap.add_argument("--no-revenue", required=True, help="saved no_revenue query performance (comma-separated pages)")
    ap.add_argument("--top", required=True, help="saved top searches by browse_sessions")
    ap.add_argument("--synonyms", help="saved list_synonyms_user output")
    ap.add_argument("--redirects", help="saved search_redirects output")
    ap.add_argument("--min-sessions", type=float, default=RULES["min_sessions"],
                    help=f"noise below this many sessions (default {RULES['min_sessions']}, from references/rules.json)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()

    def unique(rows):
        seen, out = set(), []
        for r in map(metric, rows):
            if r["query"] not in seen:
                seen.add(r["query"])
                out.append(r)
        return out

    rules = {**RULES, "min_sessions": a.min_sessions}
    result = triage(unique(read_rows(a.no_results)), unique(read_rows(a.no_revenue)), unique(read_rows(a.top)),
                    read_rows(a.synonyms), read_rows(a.redirects), rules)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "out": a.out, "summary": result["summary"]}))
    else:
        print(text)


if __name__ == "__main__":
    main()
