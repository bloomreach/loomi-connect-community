#!/usr/bin/env python3
"""Turn requested Discovery redirect fixes into a change plan, with before, after, payload and undo for each.

Usage:
  python3 redirect_plan.py --changes changes.json --redirects list.json [--redirects detail.json ...]
         --account NAME --environment staging|production [--site-group-id ID]
         [--queries query_perf.json ...] [--experiments running.json] [--today YYYY-MM-DD] [--out plan.json]

--changes is the list of changes to make (references/change-format.md). --redirects are saved search_redirects
results: list pages (every redirect, for keyword conflicts) and details (rule_id lookups, for the URL and match
type of each rule the plan touches). --queries are saved get_discovery_query_performance tables (revenue at
stake). --experiments is a saved search_discovery_experiments result for running tests.

Prints JSON: each change with its status (ready, blocked or no_change), checks (blocker, warning, nitpick),
before and after state, the exact tool call, the undo, and for new redirects a separate step to switch them on.
Deletes are listed apart, because each needs its own "yes". Changes over the batch cap are deferred.
It never calls Loomi Connect: the assistant makes each write, after confirmation. Standard library only.
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
TYPES = ("redirect_terms", "redirect_phrases", "do_not_redirect_terms", "do_not_redirect_phrases")
GOES_TO_URL = ("redirect_terms", "redirect_phrases")
ACCOUNT_LIST_ERROR = ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                      "other accounts. Ask the user to check the account name.")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(text):
    text = str(text or "no error text")
    if re.search(r"account", text, re.I) and text.count(",") >= 3:
        return ACCOUNT_LIST_ERROR
    return text[:200]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: {tool_error(d.get('error'))} This step couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    return data


def records(path):
    """List records from a list result, or a one-item list for a detail result (search_redirects with rule_id)."""
    doc = load(path)
    if isinstance(doc, dict) and "data" in doc:
        doc = doc["data"]
    if isinstance(doc, dict) and isinstance(doc.get("data"), dict):  # redirect detail is wrapped twice
        doc = doc["data"]
    if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
        doc = doc["rows"]
    if isinstance(doc, dict):
        return [doc] if "id" in doc or "query" in doc else []
    if not isinstance(doc, list):
        fail(f"{path}: expected a list of records or one redirect detail.")
    return [r for r in doc if isinstance(r, dict)]


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


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def to_ms(value, where):
    """ISO date or time, or Unix seconds or milliseconds, as Unix milliseconds (UTC)."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        fail(f"{where}: not a date or time.")
    if isinstance(value, (int, float)):
        return int(value if value > 1e11 else value * 1000)
    try:
        t = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        fail(f"{where}: {value!r} isn't an ISO date or time, or Unix milliseconds.")
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return int(t.timestamp() * 1000)


def iso(ms):
    return None if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def redirect_type(match_type):
    m = str(match_type or "").upper()
    if "DO_NOT" in m or "DONOT" in m:
        return "do_not_redirect_phrases" if "PHRASE" in m else "do_not_redirect_terms"
    if "PHRASE" in m:
        return "redirect_phrases"
    if "EXACT" in m or "TERM" in m:
        return "redirect_terms"
    return None


def index_redirects(paths):
    """Redirects by ID: list fields, plus URL, match type and audience from any detail record."""
    rules = {}
    for p in paths:
        for r in records(p):
            if r.get("ruleType") not in (None, "redirect") or r.get("id") is None:
                continue
            try:
                rid = int(r["id"])
            except (TypeError, ValueError):
                fail(f"{p}: redirect id {r.get('id')!r} isn't a number.")
            rule = rules.setdefault(rid, {"id": rid, "detail": False})
            rule["name"] = r.get("name") if r.get("name") is not None else rule.get("name")
            rule["enabled"] = r.get("enabled", rule.get("enabled"))
            rule["queries"] = [str(q.get("query")) for q in r.get("queries") or [] if isinstance(q, dict)] or rule.get("queries", [])
            rule["started_at"] = r.get("startedAt", rule.get("started_at"))
            rule["ended_at"] = r.get("endedAt", rule.get("ended_at"))
            rule["ab_test_live"] = bool(r.get("isAbTestLive")) or rule.get("ab_test_live", False)
            item = (r.get("customizationItems") or {}).get("redirect")
            if isinstance(item, dict) or r.get("audiences") is not None:
                item = item or {}
                matches = [q.get("matchType") for q in r.get("queries") or [] if isinstance(q, dict) and q.get("matchType")]
                rule["detail"] = True
                rule["url"] = item.get("url")
                rule["redirect_type"] = redirect_type(matches[0] if matches else item.get("matchType"))
                aud = [a.get("id") for a in r.get("audiences") or [] if isinstance(a, dict) and a.get("id") not in (None, -1)]
                rule["audience_id"] = aud[0] if aud else None
    return rules


def revenue_by_query(paths):
    out = {}
    for p in paths:
        for r in records(p):
            q = norm(r.get("query"))
            if q:
                out[q] = {"revenue": number(r.get("revenue")), "visits": number(r.get("visits"))}
    return out


def running_experiments(path):
    if not path:
        return []
    exps = []
    for e in records(path):
        status = norm(e.get("status") or e.get("experimentStatus") or "running")
        if status == "running":
            exps.append({"name": e.get("name"), "text": norm(json.dumps(e))})
    return exps


class Change:
    def __init__(self, n, raw):
        self.n, self.raw, self.checks = n, raw, []

    def add(self, severity, check, message):
        self.checks.append({"severity": severity, "check": check, "message": message})


def check_url(c, url, rtype):
    if rtype not in GOES_TO_URL:
        if url:
            c.add("nitpick", "url", "A do-not-redirect rule has no destination; the URL will be ignored.")
        return
    url = str(url or "").strip()
    low = url.lower()
    if not url:
        c.add("blocker", "url", "A redirect needs a destination URL.")
        return
    if re.search(r"\s", url):
        c.add("blocker", "url", "The URL contains spaces.")
    if re.match(r"^(javascript|data|mailto|file|tel|ftp):", low):
        c.add("blocker", "url", "The URL isn't a web page.")
        return
    if low.startswith("http://"):
        c.add("warning", "url", "The URL uses http, not https.")
    elif not low.startswith("https://"):
        c.add("warning", "url", "The URL has no https://, so it relies on the site to add one. Write it in full.")
    parts = urlsplit(low if "://" in low else "https://" + low.lstrip("/"))
    host = parts.hostname or ""
    if any(host == h or host.endswith("." + h) for h in RULES["placeholder_hosts"]):
        c.add("blocker", "url", f"The URL points at a placeholder host ({host}).")
    rest = parts.path + "?" + parts.query
    if any(w in rest for w in RULES["placeholder_url_words"]):
        c.add("blocker", "url", "The URL looks unfinished (a placeholder word in its path or query).")


def check_queries(c, queries, rid, rtype, rules, revenue):
    if not queries:
        c.add("blocker", "queries", "The redirect has no keywords.")
        return
    for q in queries:
        if len(q) > RULES["max_query_chars"]:
            c.add("blocker", "queries", f"Keyword {q[:40]!r}… is over {RULES['max_query_chars']} characters.")
    for q in queries:
        for other in rules.values():
            if other["id"] != rid and other.get("enabled") and norm(q) in {norm(x) for x in other.get("queries", [])}:
                c.add("blocker", "conflict", f"'{q}' is already on enabled redirect {other['id']}. Discovery silently "
                      "ignores a keyword that another redirect has: fix or remove that one first.")
    if rtype not in GOES_TO_URL:
        return
    floor = RULES["redirect_min_revenue"]
    for q in queries:
        nq = norm(q)
        if rtype == "redirect_phrases" and len(nq.split()) <= RULES["broad_query_max_words"]:
            c.add("warning", "scope", f"Phrase match on the short keyword '{q}' also catches every longer search containing it.")
        caught = [(k, v) for k, v in revenue.items()
                  if (k == nq or (rtype == "redirect_phrases" and re.search(r"(^| )" + re.escape(nq) + r"( |$)", k)))]
        for k, v in sorted(caught, key=lambda kv: -(kv[1]["revenue"] or 0)):
            if v["revenue"] is not None and v["revenue"] >= floor:
                what = "earns" if k == nq else "is caught by the phrase match and earns"
                c.add("warning", "revenue", f"'{k}' {what} {v['revenue']:.2f} from product results; the redirect takes "
                      "those shoppers away from products.")


def check_experiments(c, queries, rid, rule, exps):
    if rule and rule.get("ab_test_live"):
        c.add("blocker", "a/b test", f"Redirect {rid} is in a running A/B test; Discovery blocks changes until it ends.")
    for e in exps:
        hit = [q for q in queries if q and f'"{norm(q)}"' in e["text"]]
        if rid is not None and re.search(r"\b%d\b" % rid, e["text"]):
            hit.append(f"rule {rid}")
        if hit:
            c.add("blocker", "a/b test", f"Running experiment '{e['name']}' covers {', '.join(hit)}; wait for it to end.")


def check_schedule(c, start, end, today_ms):
    if end is not None and end <= today_ms:
        c.add("blocker", "schedule", f"The end time {iso(end)} has already passed, so the redirect would never apply.")
    if start is not None and end is not None and start >= end:
        c.add("blocker", "schedule", "The start time isn't before the end time.")


def base_args(a):
    args = {"account_name": a.account, "environment": a.environment}
    if a.site_group_id:
        args["site_group_id"] = a.site_group_id
    return args


def state(rule):
    """The parts of a redirect the plan shows and can restore. No editor names or emails."""
    return {k: rule.get(k) for k in ("id", "name", "enabled", "queries", "redirect_type", "url", "audience_id")} | {
        "started_at": iso(rule.get("started_at")), "ended_at": iso(rule.get("ended_at"))}


def plan_create(c, raw, a, rules, revenue, exps, today_ms):
    rtype = raw.get("redirect_type")
    if rtype not in TYPES:
        c.add("blocker", "type", f"redirect_type must be one of {', '.join(TYPES)}.")
    queries = [str(q).strip() for q in raw.get("queries") or [] if str(q).strip()]
    start = to_ms(raw.get("started_at"), f"change {c.n} started_at")
    end = to_ms(raw.get("ended_at"), f"change {c.n} ended_at")
    check_queries(c, queries, None, rtype, rules, revenue)
    check_url(c, raw.get("destination_url"), rtype)
    check_experiments(c, queries, None, None, exps)
    check_schedule(c, start, end, today_ms)
    args = dict(base_args(a), queries=queries, redirect_type=rtype, enabled=False)
    for k, v in (("destination_url", raw.get("destination_url") if rtype in GOES_TO_URL else None),
                 ("name", raw.get("name")), ("audience_id", raw.get("audience_id")), ("started_at", start), ("ended_at", end)):
        if v not in (None, ""):
            args[k] = v
    shown = {k: (iso(v) if k in ("started_at", "ended_at") else v) for k, v in args.items() if k not in base_args(a)}
    out = {"action": "create", "before": None, "after": shown,
           "payload": {"tool": "create_redirect", "arguments": args},
           "undo": {"tool": "delete_redirect", "arguments": dict(base_args(a), rule_id="<id returned by the create>"),
                    "note": "Deleting the new rule removes it completely."},
           "live_impact": "None: created disabled."}
    if raw.get("enabled") is not False:
        out["then_enable"] = {"tool": "update_redirect", "arguments": dict(base_args(a), rule_id="<id returned by the create>",
                                                                          enabled=True),
                              "live_impact": "Live for every shopper who searches " + ", ".join(f"'{q}'" for q in queries)
                                             + " once Discovery syncs (seconds to minutes).",
                              "undo": {"tool": "update_redirect", "arguments": dict(
                                  base_args(a), rule_id="<id returned by the create>", enabled=False)}}
    return out


FIELDS = ("queries", "redirect_type", "destination_url", "name", "enabled", "audience_id", "started_at", "ended_at")


def plan_update(c, raw, a, rules, revenue, exps, today_ms):
    rid = raw.get("rule_id")
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        c.add("blocker", "rule", "An update needs the redirect's numeric rule_id.")
        return {"action": "update", "rule_id": rid}
    rule = rules.get(rid)
    if not rule:
        c.add("blocker", "rule", f"Redirect {rid} isn't in the saved search_redirects results: fetch it first.")
        return {"action": "update", "rule_id": rid}
    if not rule.get("detail"):
        c.add("blocker", "rule", f"Fetch redirect {rid} with search_redirects rule_id={rid} first: the list has no URL "
              "or match type, so the change and its undo can't be planned.")
        return {"action": "update", "rule_id": rid, "before": state(rule)}
    before = {"queries": rule.get("queries"), "redirect_type": rule.get("redirect_type"), "destination_url": rule.get("url"),
              "name": rule.get("name"), "enabled": rule.get("enabled"), "audience_id": rule.get("audience_id"),
              "started_at": rule.get("started_at"), "ended_at": rule.get("ended_at")}
    want = {}
    for k in FIELDS:
        if k in raw and raw[k] is not None:
            v = raw[k]
            if k == "queries":
                v = [str(q).strip() for q in v if str(q).strip()]
            if k in ("started_at", "ended_at"):
                v = to_ms(v, f"change {c.n} {k}")
            want[k] = v
    if "redirect_type" in want and want["redirect_type"] not in TYPES:
        c.add("blocker", "type", f"redirect_type must be one of {', '.join(TYPES)}.")
    changed = {k: v for k, v in want.items()
               if (norm(v) if k == "queries" else v) != (norm(before[k]) if k == "queries" else before[k])}
    if "queries" in changed and [norm(q) for q in changed["queries"]] == [norm(q) for q in before["queries"] or []]:
        changed.pop("queries")
    if not changed:
        c.add("nitpick", "no change", "The redirect already has these values.")
        return {"action": "update", "rule_id": rid, "before": state(rule), "no_change": True}
    after = dict(before, **changed)
    queries = after["queries"] or []
    check_experiments(c, queries, rid, rule, exps)
    if "queries" in changed:
        check_queries(c, queries, rid, after["redirect_type"], rules, revenue)
    if changed.keys() & {"destination_url", "redirect_type"}:
        check_url(c, after["destination_url"], after["redirect_type"])
    if after.get("enabled") and changed.keys() & {"enabled", "redirect_type", "destination_url"} and "queries" not in changed:
        check_queries(c, queries, rid, after["redirect_type"], {}, revenue)  # revenue and scope; conflicts unchanged
    check_schedule(c, after["started_at"], after["ended_at"], today_ms)
    undo_args, manual = dict(base_args(a), rule_id=rid), []
    for k in changed:
        if before[k] is None and k in ("started_at", "ended_at", "audience_id"):
            manual.append(k)
        else:
            undo_args[k] = before[k] if k != "destination_url" else (before[k] or "")
    impact = ("Off for all shoppers once Discovery syncs." if changed.get("enabled") is False else
              "Live for every shopper who searches these keywords once Discovery syncs." if after.get("enabled") else
              "None while the redirect is disabled.")
    out = {"action": "update", "rule_id": rid,
           "before": {k: (iso(v) if k in ("started_at", "ended_at") else v) for k, v in before.items() if k in changed},
           "after": {k: (iso(v) if k in ("started_at", "ended_at") else v) for k, v in changed.items()},
           "payload": {"tool": "update_redirect", "arguments": dict(base_args(a), rule_id=rid, **changed)},
           "undo": {"tool": "update_redirect", "arguments": undo_args}, "live_impact": impact}
    if manual:
        out["undo"]["note"] = (f"update_redirect can't clear {', '.join(manual)} (an omitted field keeps its value); "
                               "undo that part in the Discovery dashboard.")
    return out


def plan_delete(c, raw, a, rules, exps):
    try:
        rid = int(raw.get("rule_id"))
    except (TypeError, ValueError):
        c.add("blocker", "rule", "A delete needs the redirect's numeric rule_id.")
        return {"action": "delete", "rule_id": raw.get("rule_id"), "separate_yes": True}
    rule = rules.get(rid)
    if not rule or not rule.get("detail"):
        c.add("blocker", "rule", f"Fetch redirect {rid} with search_redirects rule_id={rid} first: its full state is "
              "the only way to undo a delete.")
        return {"action": "delete", "rule_id": rid, "separate_yes": True}
    check_experiments(c, rule.get("queries") or [], rid, rule, exps)
    recreate = dict(base_args(a), queries=rule.get("queries") or [], redirect_type=rule.get("redirect_type"),
                    enabled=bool(rule.get("enabled")))
    for k, v in (("destination_url", rule.get("url")), ("name", rule.get("name")), ("audience_id", rule.get("audience_id")),
                 ("started_at", rule.get("started_at")), ("ended_at", rule.get("ended_at"))):
        if v not in (None, ""):
            recreate[k] = v
    if not rule.get("redirect_type"):
        c.add("blocker", "rule", f"Redirect {rid}'s match type is unknown, so it couldn't be recreated: don't delete it; "
              "disable it instead.")
    c.add("warning", "permanent", "Deletes can't be undone in Discovery. The undo recreates the redirect with a new ID "
          "and no edit history. Disabling it is the reversible alternative.")
    return {"action": "delete", "rule_id": rid, "before": state(rule), "after": None, "separate_yes": True,
            "payload": {"tool": "delete_redirect", "arguments": dict(base_args(a), rule_id=rid)},
            "undo": {"tool": "create_redirect", "arguments": recreate},
            "live_impact": "Off for all shoppers once Discovery syncs, permanently." if rule.get("enabled") else
                           "None: the redirect is disabled."}


def day(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # keywords can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--changes", required=True, help="JSON list of changes (references/change-format.md)")
    ap.add_argument("--redirects", action="append", required=True, help="saved search_redirects list page or detail (repeat)")
    ap.add_argument("--queries", action="append", default=[], help="saved get_discovery_query_performance table (repeat)")
    ap.add_argument("--experiments", help="saved search_discovery_experiments result with running tests")
    ap.add_argument("--account", required=True, help="the Discovery account name the user confirmed")
    ap.add_argument("--environment", required=True, choices=["staging", "production"])
    ap.add_argument("--site-group-id", help="site group ID or site name, if the account has sites")
    ap.add_argument("--today", type=day, help="YYYY-MM-DD to judge schedules against (default: today, UTC)")
    ap.add_argument("--out", help="also write the plan (with every undo) to this file")
    a = ap.parse_args()
    today = a.today or datetime.now(timezone.utc)
    today_ms = int(today.timestamp() * 1000)

    raw_changes = load(a.changes)
    if isinstance(raw_changes, dict) and isinstance(raw_changes.get("changes"), list):
        raw_changes = raw_changes["changes"]
    if not isinstance(raw_changes, list) or not all(isinstance(x, dict) for x in raw_changes):
        fail(f"{a.changes}: expected a JSON list of change objects (references/change-format.md).")
    rules = index_redirects(a.redirects)
    revenue = revenue_by_query(a.queries)
    exps = running_experiments(a.experiments)
    cap = RULES["max_changes_per_batch"]

    planned, deferred = [], []
    for n, raw in enumerate(raw_changes, 1):
        if len(planned) >= cap:
            deferred.append({"n": n, "action": raw.get("action"), "rule_id": raw.get("rule_id"),
                             "queries": raw.get("queries"), "reason": raw.get("reason")})
            continue
        c = Change(n, raw)
        action = raw.get("action")
        if action == "create":
            body = plan_create(c, raw, a, rules, revenue, exps, today_ms)
        elif action == "update":
            body = plan_update(c, raw, a, rules, revenue, exps, today_ms)
        elif action == "delete":
            body = plan_delete(c, raw, a, rules, exps)
        else:
            c.add("blocker", "action", "action must be create, update or delete.")
            body = {"action": action}
        status = ("blocked" if any(x["severity"] == "blocker" for x in c.checks)
                  else "no_change" if body.get("no_change") else "ready")
        body.pop("no_change", None)
        order = {"blocker": 0, "warning": 1, "nitpick": 2}
        planned.append(dict({"n": n, "status": status, "reason": raw.get("reason")}, **body,
                            checks=sorted(c.checks, key=lambda x: order[x["severity"]])))

    ready = [p for p in planned if p["status"] == "ready"]
    out = {"ok": True, "account": a.account, "environment": a.environment, "site_group_id": a.site_group_id,
           "today": today.strftime("%Y-%m-%d"), "batch_cap": cap, "changes": planned, "deferred": deferred,
           "counts": {s: sum(1 for p in planned if p["status"] == s) for s in ("ready", "blocked", "no_change")},
           "confirm": {"batch": [p["n"] for p in ready if p["action"] != "delete"],
                       "deletes_each_separately": [p["n"] for p in ready if p["action"] == "delete"]}}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
