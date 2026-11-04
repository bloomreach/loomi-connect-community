#!/usr/bin/env python3
"""Work out how long each Bloomreach Engagement voucher pool will last, and what uses it, from saved tool results.

Usage:
  python3 voucher_pool_health.py --pools FILE [--pool-detail FILE ...] [--codes POOL=FILE ...]
      [--objects KIND=FILE ...] [--calendar FILE ...] [--assignments POOL=COUNT_OR_FILE ...]
      [--previous FILE --previous-date YYYY-MM-DD] [--expiry POOL=YYYY-MM-DD ...] [--denied KIND ...]
      [--today YYYY-MM-DD] [--out report.json]

POOL is a pool ID or its exact name. NAME=VALUE inputs are split on the first "=".
  --pools          the saved search_voucher_pools list (_id, name, total, available)
  --pool-detail    a saved search_voucher_pools detail (one pool_id), for its used_by list
  --codes          saved list_voucher_codes pages for one pool (repeat for each page; at most
                   max_code_pages in rules.json). Codes are read only to count statuses and assignment
                   times; they are never printed. Used for the burn rate only when neither --previous
                   nor --assignments covers the pool
  --objects        a saved list or detail of scenarios, email or SMS campaigns or weblayers, with
                   KIND scenario, email, sms or banner; used for statuses and to find Jinja voucher
                   references (vouchers['<pool name>'])
  --calendar       a saved get_campaign_calendar response (repeat for each week)
  --assignments    codes assigned from a pool in the burn window, counted another way (a number, or a
                   saved aggregate EQL result on a voucher event as a .json path; only each row's
                   first value, the count column, is added up)
  --previous       an earlier saved search_voucher_pools list, with --previous-date, so the burn rate
                   can come from the change in available codes
  --expiry         the date a pool's codes expire (Engagement returns no expiry on codes)
  --denied         an object kind whose tool returned HTTP 403 (not checked)

Prints JSON (or writes it to --out): each pool with its counts, burn rate and where it came from,
days of cover, planned sends and their audience, users, expiry checks, a red, amber, green,
unknown or not_in_use rating, and findings with priority high, medium or low. Thresholds come
from references/rules.json. Dates are UTC.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import datetime
import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
PRIORITY = {"high": 0, "medium": 1, "low": 2}
RAG_ORDER = {"red": 0, "amber": 1, "unknown": 2, "green": 3, "not_in_use": 4}
KINDS = ("scenario", "email", "sms", "banner")
CONTEXT_WORDS = re.compile(r"project|organi[sz]ation|account|access|denied|forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|too many requests", re.I)
URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s'\"<>]+")
DAY = 86400


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def redact(text):
    return URL.sub("[url]", str(text))


def load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        fail(f"can't read references/rules.json ({e.strerror or e}).")
    except json.JSONDecodeError as e:
        fail(f"references/rules.json is not valid JSON ({e}).")


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


def load(path, allow_missing_item=False):
    """Read a saved tool result. A context error stops the run; a not-found on the item returns None."""
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
        err = redact(data.get("error") or "no error text")
        if CONTEXT_WORDS.search(err) or not allow_missing_item:
            fail(f"{path}: Loomi Connect returned an error: {err}. Fix the project or access before reading anything "
                 "else from this run; don't treat it as 'nothing found'.")
        if re.search(r"not found|does not exist|no such", err, re.I):
            return None
        fail(f"{path}: Loomi Connect returned an error: {err}.")
    if isinstance(data, dict) and "success" in data and "data" in data:
        data = data["data"]
    return data


def records(data):
    """Dicts that look like objects (have an id), from a list, a detail or a wrapped response."""
    if isinstance(data, dict):
        for key in ("data", "items", "results", "campaigns", "scenarios", "banners", "entries"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def rid(r):
    for k in ("_id", "id", "campaign_id", "scenario_id", "banner_id"):
        if r.get(k) not in (None, ""):
            return str(r[k])
    return None


def pair(text):
    name, sep, value = text.partition("=")
    if not sep or not name.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE, got {text!r}")
    return name.strip(), value.strip()


def parse_day(s, label):
    try:
        d = datetime.date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        fail(f"{label}: {s!r} isn't a date (YYYY-MM-DD).")
    return d


def day_ts(d):
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


def ts_day(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date().isoformat()


def as_ts(v):
    """A Unix timestamp (seconds) from a number, a millisecond number or an ISO date."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*", v)):
        x = number(v)
        return x / 1000 if x is not None and x > 1e11 else x
    if isinstance(v, str) and v.strip():
        try:
            dt = datetime.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


def count_value(value, label):
    """A count from a plain number or a saved aggregate EQL result (a path ending .json). Only each
    row's first value (the count column) is added up, so extra metric columns aren't counted."""
    if value.lower().endswith(".json"):
        data = load(value)
        rows = data.get("rows") if isinstance(data, dict) else None
        if rows is None and isinstance(data, dict) and isinstance(data.get("data"), dict):
            rows = data["data"].get("rows")
        if not isinstance(rows, list):
            fail(f"{label}: no EQL rows found in {value}; save the execute_analytics_eql result or give a number.")
        total = 0
        for r in rows:
            vals = r.get("values") if isinstance(r, dict) else None
            if vals:
                x = number(vals[0])
                total += int(x) if x is not None and x > 0 else 0
        return total
    x = number(value)
    if x is None or x < 0 or not re.fullmatch(r"\s*[\d,]+(\.\d+)?\s*", value):
        fail(f"{label}: {value!r} is neither a saved EQL result (.json) nor a count.")
    return int(x)


def whole(v):
    """A count from a tool value, or None when it's missing (never silently 0)."""
    x = number(v)
    return None if x is None or x < 0 else int(x)


def fmt(fr, places=2):
    if fr is None:
        return None
    return round(float(fr), places)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rules = load_rules()
    ap = argparse.ArgumentParser(description="Voucher pool days of cover, users and expiry from saved Loomi Connect results.")
    ap.add_argument("--pools", required=True, help="saved search_voucher_pools list")
    ap.add_argument("--pool-detail", action="append", default=[], help="saved search_voucher_pools detail (repeatable)")
    ap.add_argument("--codes", action="append", default=[], type=pair, help="POOL=FILE: a saved list_voucher_codes page (repeatable)")
    ap.add_argument("--objects", action="append", default=[], type=pair, help="KIND=FILE: saved scenarios, email, sms or banner list or detail (repeatable)")
    ap.add_argument("--calendar", action="append", default=[], help="saved get_campaign_calendar response (repeatable)")
    ap.add_argument("--assignments", action="append", default=[], type=pair, help="POOL=COUNT_OR_FILE: codes assigned in the burn window, from EQL")
    ap.add_argument("--previous", help="an earlier saved search_voucher_pools list")
    ap.add_argument("--previous-date", help="the date the --previous list was saved (YYYY-MM-DD)")
    ap.add_argument("--expiry", action="append", default=[], type=pair, help="POOL=YYYY-MM-DD: when the pool's codes expire")
    ap.add_argument("--denied", action="append", default=[], choices=list(KINDS), help="object kind whose tool returned HTTP 403")
    ap.add_argument("--today", help="today's date, YYYY-MM-DD (default: the system date, UTC)")
    ap.add_argument("--burn-window-days", type=int, default=rules["burn_window_days"], help="days of assignments for the burn rate (rules: burn_window_days)")
    ap.add_argument("--horizon-days", type=int, default=rules["horizon_days"], help="days of planned sends to read (rules: horizon_days)")
    ap.add_argument("--out", help="write the JSON report here instead of printing it")
    a = ap.parse_args()
    if a.burn_window_days < 1 or a.horizon_days < 1:
        fail("--burn-window-days and --horizon-days must be at least 1.")
    if bool(a.previous) != bool(a.previous_date):
        fail("--previous and --previous-date go together.")

    today = parse_day(a.today, "--today") if a.today else datetime.datetime.now(datetime.timezone.utc).date()
    t0 = day_ts(today)
    win_start = t0 - a.burn_window_days * DAY
    horizon_end = t0 + a.horizon_days * DAY
    live_kinds = set(rules["live_kinds"])
    live_statuses = {s.lower() for s in rules["live_statuses"]}
    prefixes = sorted(rules["used_by_prefixes"].items(), key=lambda kv: -len(kv[0]))

    # Pools
    pools = {}
    for r in records(load(a.pools)):
        pid = rid(r)
        if pid:
            pools[pid] = {"pool_id": pid, "name": str(r.get("name") or ""), "total": whole(r.get("total")),
                          "available": whole(r.get("available")), "used_by": None}
    if not pools:
        fail(f"{a.pools}: no voucher pools found. If the project has none, there's nothing to check.")
    by_name = {}
    for p in pools.values():
        by_name.setdefault(p["name"], []).append(p["pool_id"])

    def pool_key(key, label):
        if key in pools:
            return key
        ids = by_name.get(key) or []
        if len(ids) == 1:
            return ids[0]
        fail(f"{label}: {key!r} isn't a pool ID or a unique pool name in --pools.")

    for path in a.pool_detail:
        d = load(path, allow_missing_item=True)
        for r in records(d) if d is not None else []:
            pid = rid(r)
            if pid in pools:
                pools[pid]["used_by"] = [str(u) for u in (r.get("used_by") or [])]

    # Codes: counted, never kept beyond this block
    codes = {}
    for key, path in a.codes:
        pid = pool_key(key, "--codes")
        d = load(path)
        rows = records(d)
        raw = d if isinstance(d, dict) else {}
        st = codes.setdefault(pid, {"seen": {}, "matched": None})
        m = number(raw.get("matched")) if isinstance(raw, dict) else None
        if m is not None:
            st["matched"] = int(m)
        for i, r in enumerate(rows):
            if "status" not in r:
                continue
            k = r.get("code")
            k = ("code", str(k)) if k not in (None, "") else ("row", path, i)
            exp = None
            for f in rules["code_expiry_fields"]:
                if r.get(f) not in (None, ""):
                    exp = as_ts(r[f])
                    break
            st["seen"][k] = (str(r.get("status") or "").lower(), as_ts(r.get("assigned_time")), exp)

    # Objects (scenarios, campaigns, weblayers)
    objects = {}
    for kind, path in a.objects:
        if kind not in KINDS:
            fail(f"--objects: kind {kind!r} must be one of {', '.join(KINDS)}.")
        d = load(path, allow_missing_item=True)
        for r in records(d) if d is not None else []:
            oid = rid(r)
            if not oid:
                continue
            prev = objects.get((kind, oid), {})
            text = json.dumps(r, ensure_ascii=False, sort_keys=True)
            objects[(kind, oid)] = {
                "kind": kind, "id": oid, "name": r.get("name") or prev.get("name"),
                "status": (r.get("status") if r.get("status") is not None else prev.get("status")),
                "archived": bool(r.get("archived")) or prev.get("archived", False),
                "text": prev.get("text", "") + "\n" + text,
            }

    # Calendar entries
    entries = []
    for path in a.calendar:
        stack = [load(path)]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if x.get("campaign_id") is not None and isinstance(x.get("times"), list):
                    entries.append(x)
                else:
                    stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)

    assignments = {pool_key(k, "--assignments"): count_value(v, "--assignments") for k, v in a.assignments}
    expiries = {pool_key(k, "--expiry"): day_ts(parse_day(v, "--expiry")) for k, v in a.expiry}
    previous = {}
    prev_days = None
    if a.previous:
        pd = parse_day(a.previous_date, "--previous-date")
        prev_days = (today - pd).days
        if prev_days <= 0:
            fail("--previous-date must be before --today.")
        for r in records(load(a.previous)):
            if rid(r):
                pt, pa = whole(r.get("total")), whole(r.get("available"))
                if pt is not None and pa is not None:
                    previous[rid(r)] = (pt, pa)

    def is_live(kind, status, archived):
        return kind in live_kinds and not archived and status is not None and str(status).lower() in live_statuses

    out_pools = []
    for pid in sorted(pools, key=lambda k: (pools[k]["name"].lower(), k)):
        p = pools[pid]
        findings = []

        # Users: used_by, then Jinja and ID references
        users = {}
        for u in p["used_by"] or []:
            kind, oid = "other", u
            for pre, k in prefixes:
                if u.startswith(pre + "_"):
                    kind, oid = k, u[len(pre) + 1:]
                    break
            users[(kind, oid)] = {"kind": kind, "id": oid, "found_by": ["used_by"]}
        name_pat = re.compile(r"vouchers\s*\[\s*(['\"])" + re.escape(p["name"]) + r"\1\s*\]") if p["name"] else None
        for (kind, oid), o in sorted(objects.items()):
            how = []
            if name_pat and name_pat.search(o["text"].replace('\\"', '"')):
                how.append("jinja")
            if len(pid) >= rules["min_id_chars"] and pid in o["text"]:
                how.append("pool id")
            if how:
                u = users.setdefault((kind, oid), {"kind": kind, "id": oid, "found_by": []})
                u["found_by"] = sorted(set(u["found_by"]) | set(how))
        user_list = []
        for (kind, oid), u in sorted(users.items()):
            o = objects.get((kind, oid))
            status = o["status"] if o else None
            archived = o["archived"] if o else False
            live = is_live(kind, status, archived)
            user_list.append({"kind": kind, "id": oid, "name": o["name"] if o else None,
                              "status": ("archived" if archived else (status if status is not None else "unknown")),
                              "live": live, "found_by": u["found_by"]})
        live_users = [u for u in user_list if u["live"]]
        unknown_users = [u for u in user_list if u["status"] == "unknown" and u["kind"] in live_kinds]

        # Codes
        cs = codes.get(pid)
        counts = None
        burn_codes = None
        codes_complete = False
        expired_available = expiring_before = None
        code_exp = []
        if cs:
            vals = list(cs["seen"].values())
            counts = {"loaded": len(vals)}
            for s in ("available", "assigned", "redeemed"):
                counts[s] = sum(1 for v in vals if v[0] == s)
            expected = cs["matched"] if cs["matched"] is not None else p["total"]
            # Complete only when every code was loaded: page order isn't guaranteed, so pages that
            # happen to reach back past the window can still miss assignments inside it.
            codes_complete = expected is not None and len(vals) >= expected
            in_win = sum(1 for v in vals if v[1] is not None and win_start <= v[1] < t0)
            burn_codes = (in_win, codes_complete)
            code_exp = [(v[0], v[2]) for v in vals if v[2] is not None]

        # Burn rate
        burn = None
        source = None
        partial = False
        avail = p["available"]
        counts_ok = avail is not None and p["total"] is not None
        if pid in previous and counts_ok:
            ptot, pav = previous[pid]
            used = pav + max(0, p["total"] - ptot) - p["available"]
            burn, source = Fraction(max(0, used), prev_days), f"change in available codes over {prev_days} days"
        elif pid in assignments:
            burn, source = Fraction(assignments[pid], a.burn_window_days), "voucher event (EQL)"
        elif burn_codes and burn_codes[1]:
            burn, source = Fraction(burn_codes[0], a.burn_window_days), "code assigned_time"
        elif burn_codes:
            burn, source, partial = Fraction(burn_codes[0], a.burn_window_days), "code assigned_time (newest pages only)", True
        cover = (Fraction(avail) / burn) if burn and avail is not None else None
        run_out = ts_day(t0 + int(cover * DAY)) if cover is not None else None

        # Planned sends
        user_ids = {u["id"]: u for u in user_list}
        planned = []
        demand = 0
        demand_known = True
        last_send = None
        for e in entries:
            cid = str(e.get("campaign_id"))
            if cid not in user_ids:
                continue
            u = user_ids[cid]
            starts = sorted(t for t in (as_ts((t or {}).get("start") if isinstance(t, dict) else t) for t in e["times"])
                            if t is not None and t0 <= t < horizon_end)
            if not starts:
                continue
            res = e.get("results") or {}
            reach = number(res.get("potential_reach"))
            if reach is None:
                reach = number(res.get("reach"))
            active = u["live"] or str(e.get("status") or "").lower() in live_statuses
            item = {"campaign": e.get("campaign_name") or u["name"], "campaign_id": cid, "channel": e.get("channel"),
                    "active": active, "sends": len(starts), "next_send": ts_day(starts[0]), "last_send": ts_day(starts[-1]),
                    "audience_per_send": int(reach) if reach is not None else None}
            planned.append(item)
            if active:
                last_send = max(last_send or 0, starts[-1])
                if reach is None:
                    demand_known = False
                else:
                    demand += int(reach) * len(starts)
        planned.sort(key=lambda x: (x["next_send"], str(x["campaign"])))
        has_active_plan = any(x["active"] for x in planned)

        # Expiry
        exp_ts = expiries.get(pid)
        if exp_ts is None and code_exp:
            exp_ts = min(t for _, t in code_exp)
        if code_exp:
            expired_available = sum(1 for s, t in code_exp if s == "available" and t < t0)
            if last_send:
                expiring_before = sum(1 for s, t in code_exp if s == "available" and t < last_send)

        live = bool(live_users) or has_active_plan
        rag = "green"
        if avail is None:
            if live:
                rag = "unknown"
            findings.append(("medium", "counts_missing", "search_voucher_pools returned no available count for this pool, so cover, demand and empty checks were skipped; fetch the pool again."))
        if avail == 0 and live:
            rag = "red"
            findings.append(("high", "empty_but_live", f"No codes left, but {len(live_users) or 'a planned send'} live user(s) still hand them out: those sends skip or fail."))
        if cover is not None and live and cover < rules["red_days_cover"] and p["available"] > 0:
            rag = "red"
            findings.append(("high", "runs_out", f"About {fmt(cover, 1)} days of cover at {fmt(burn)} codes a day (runs out around {run_out})."))
        elif cover is not None and live and cover < rules["amber_days_cover"] and avail > 0:
            rag = "red" if rag == "red" else "amber"
            findings.append(("medium", "low_cover", f"About {fmt(cover, 1)} days of cover at {fmt(burn)} codes a day (runs out around {run_out})."))
        if has_active_plan and avail is not None and demand > avail > 0:
            rag = "red"
            findings.append(("high", "demand_exceeds", f"Planned sends in the next {a.horizon_days} days reach about {demand} customers, more than the {p['available']} codes left."))
        elif has_active_plan and avail is not None and avail > 0 and demand >= Fraction(str(rules["amber_demand_share"])) * p["available"]:
            rag = "red" if rag == "red" else "amber"
            findings.append(("medium", "demand_near", f"Planned sends reach about {demand} customers, close to the {p['available']} codes left."))
        if has_active_plan and not demand_known:
            findings.append(("low", "demand_unknown", "A planned send has no reach in the calendar, so its demand isn't counted."))
        if exp_ts is not None and live:
            if exp_ts < t0:
                rag = "red"
                findings.append(("high", "expired_in_use", f"Codes expired on {ts_day(exp_ts)}, but the pool is still in live use."))
            elif last_send and exp_ts < last_send:
                rag = "red"
                findings.append(("high", "expiry_before_send", f"Codes expire on {ts_day(exp_ts)}, before the last planned send on {ts_day(last_send)}."))
            elif exp_ts < t0 + rules["expiry_warning_days"] * DAY:
                rag = "red" if rag == "red" else "amber"
                findings.append(("medium", "expiry_soon", f"Codes expire on {ts_day(exp_ts)}."))
        if expired_available:
            findings.append(("medium", "expired_codes_available", f"{expired_available} available codes have already expired."))
        if live and burn is None and not has_active_plan and avail is not None and avail > 0:
            rag = "unknown" if rag == "green" else rag
            findings.append(("medium", "burn_unknown", "In live use, but no burn rate could be measured: load the codes, count a voucher event, or compare with an earlier snapshot."))
        if partial:
            findings.append(("low", "burn_lower_bound", "Only some code pages were loaded (not the whole pool), so the burn rate comes from the newest pages and is a lower bound."))
        if not live:
            rag = "not_in_use"
            if not user_list and p["used_by"] is not None:
                findings.append(("low", "unused", "Nothing references this pool (used_by is empty and no Jinja reference was found)."))
            elif not user_list:
                findings.append(("low", "users_not_checked", "Pool detail not loaded and no reference found in the definitions checked."))
            elif unknown_users:
                findings.append(("medium", "status_unknown", f"{len(unknown_users)} user(s) whose status wasn't loaded; load them before calling this pool unused."))
            else:
                findings.append(("low", "no_live_use", "Only drafts, inactive or archived objects reference this pool."))
        elif unknown_users:
            findings.append(("low", "status_unknown", f"{len(unknown_users)} further user(s) whose status wasn't loaded."))

        findings.sort(key=lambda f: (PRIORITY[f[0]], f[1]))
        out_pools.append({
            "pool_id": pid, "name": p["name"], "total": p["total"], "available": p["available"],
            "codes": counts, "burn_per_day": fmt(burn), "burn_source": source, "burn_window_days": a.burn_window_days,
            "days_of_cover": fmt(cover, 1), "runs_out_around": run_out,
            "planned_sends": planned, "planned_demand": demand if has_active_plan else None,
            "expiry": ts_day(exp_ts) if exp_ts is not None else None,
            "expired_available_codes": expired_available, "available_codes_expiring_before_last_send": expiring_before,
            "users": user_list, "live_users": len(live_users), "rag": rag,
            "findings": [{"priority": pr, "kind": k, "detail": d} for pr, k, d in findings],
        })

    out_pools.sort(key=lambda x: (RAG_ORDER[x["rag"]], x["days_of_cover"] if x["days_of_cover"] is not None else math.inf, x["name"].lower(), x["pool_id"]))
    summary = {r: sum(1 for x in out_pools if x["rag"] == r) for r in RAG_ORDER}
    result = {"ok": True, "today": today.isoformat(), "horizon_days": a.horizon_days, "pools": out_pools,
              "summary": summary, "not_checked": sorted(set(a.denied)),
              "objects_checked": {k: sum(1 for (kk, _) in objects if kk == k) for k in KINDS},
              "calendar_entries": len(entries)}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"--out {a.out}: can't write the file ({e.strerror or e}).")
        print(json.dumps({"ok": True, "out": a.out, "summary": summary}))
    else:
        print(text)


if __name__ == "__main__":
    main()
