#!/usr/bin/env python3
"""Rank trending search queries from Loomi Connect `get_discovery_query_performance` output.

Usage:
  python3 rank_trends.py --baseline -2.86 [--min-sessions 30] [--top 15] page1.json [page2.json ...]

Each input file is the raw JSON returned by get_discovery_query_performance (current period
with prev_* columns). --baseline is the overall search browse_sessions % change for the same
window, from get_discovery_search_performance, so trends are measured against site-wide growth.
Prints JSON with rising, new and falling queries. A query exactly in line with the baseline is
neither rising nor falling. Rows whose query differs only by case or spaces ("dress", "Dress ")
are added together and listed under "merged_variants"; the same row repeated across pages is
counted once. Standard library only; no network access.
"""
import argparse
import json
import math
import sys


def num(v):
    """A number from a Loomi Connect value ("$1,234.50", "12%", 7); None if missing or unreadable."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for ch in "$£€,":
        s = s.replace(ch, "")
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    if s.lower() in ("", "na", "n/a", "-", "—", "null"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of rows."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
    return doc


def rows_of(data):
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    return data.get("rows", []) if isinstance(data, dict) else []


def load_rows(paths):
    """Return (merged rows, merged variants). Repeats of the same query text keep the larger row."""
    exact = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = check(json.load(f), path)
        for r in rows_of(data):
            q = str(r.get("query") or "")
            if not q.strip():
                continue
            old = exact.get(q)
            if old is None or (num(r.get("browse_sessions")) or 0) > (num(old.get("browse_sessions")) or 0):
                exact[q] = r
    groups = {}
    for q, r in exact.items():
        groups.setdefault(" ".join(q.lower().split()), []).append(r)
    rows, variants = [], []
    for key, rs in groups.items():
        if len(rs) == 1:
            rows.append(rs[0])
            continue
        rs.sort(key=lambda r: -(num(r.get("browse_sessions")) or 0))
        merged = {"query": key}
        for col in ("browse_sessions", "prev_browse_sessions", "revenue"):
            vals = [num(r.get(col)) for r in rs]
            merged[col] = sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
        for col in ("conversion_rate", "bounce_rate"):  # weighted by sessions
            pairs = [(num(r.get(col)), num(r.get("browse_sessions")) or 0) for r in rs]
            pairs = [(v, w) for v, w in pairs if v is not None]
            w = sum(w for _, w in pairs)
            merged[col] = round(sum(v * w for v, w in pairs) / w, 2) if w else None
        rows.append(merged)
        variants.append({"query": key, "merged": [r.get("query") for r in rs]})
    return rows, variants


def score(rows, baseline_pct, min_sessions):
    growth = 1 + baseline_pct / 100
    rising, new, falling = [], [], []
    missing = 0
    for r in rows:
        cur, prev = num(r.get("browse_sessions")), num(r.get("prev_browse_sessions"))
        if cur is None or prev is None:
            missing += 1
        cur, prev = cur or 0, prev or 0
        if max(cur, prev) < min_sessions:
            continue
        expected = prev * growth
        item = {
            "query": r["query"],
            "sessions": cur,
            "prev_sessions": prev,
            "change_pct": round((cur / prev - 1) * 100, 1) if prev else None,
            "vs_baseline_pct": round((cur / expected - 1) * 100, 1) if expected else None,
            "extra_sessions": round(cur - expected),
            "revenue": num(r.get("revenue")),
            "conversion_rate": num(r.get("conversion_rate")),
            "bounce_rate": num(r.get("bounce_rate")),
        }
        # Lift weighted by volume, so a big query growing 30% outranks a tiny one growing 200%.
        item["trend_score"] = round(item["extra_sessions"] / math.sqrt(max(expected, 1)), 2)
        if prev == 0:
            new.append(item)
        elif item["extra_sessions"] > 0:
            rising.append(item)
        elif item["extra_sessions"] < 0:
            falling.append(item)
    rising.sort(key=lambda i: i["trend_score"], reverse=True)
    falling.sort(key=lambda i: i["trend_score"])
    new.sort(key=lambda i: i["sessions"], reverse=True)
    return rising, new, falling, missing


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--baseline", type=float, required=True, help="site search sessions %% change")
    ap.add_argument("--min-sessions", type=int, default=30)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    rows, variants = load_rows(a.files)
    rising, new, falling, missing = score(rows, a.baseline, a.min_sessions)
    out = {
        "queries_considered": len(rows),
        "baseline_change_pct": a.baseline,
        "rising": rising[:a.top],
        "new": new[:a.top],
        "falling": falling[:a.top],
        "merged_variants": variants,
    }
    if missing:
        out["missing_sessions_note"] = (f"{missing} queries had a missing or unreadable session count, "
                                        "counted as 0.")
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
