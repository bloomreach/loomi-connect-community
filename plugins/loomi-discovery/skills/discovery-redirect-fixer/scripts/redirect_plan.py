#!/usr/bin/env python3
"""Plan Discovery redirect fixes before writing them, and check the writes afterwards.

Usage:
  python3 redirect_plan.py plan --changes changes.json --redirects list.json [--redirects detail.json ...]
         --account NAME --environment staging|production [--site-group-id ID]
         [--queries query_perf.json ...] [--experiments experiments.json] [--today YYYY-MM-DD] [--out plan.json]
  python3 redirect_plan.py verify --plan plan.json --readback N=readback.json [--readback N=file ...] [--out result.json]

plan: --changes is the list of changes to make (references/change-format.md). --redirects are saved search_redirects
results: list pages (every redirect, for keyword conflicts) and details (rule_id lookups, for the URL and match
type of each rule the plan touches). --queries are saved get_discovery_query_performance tables (revenue at
stake). --experiments is a saved search_discovery_experiments result. Prints the plan in the shape in
docs/skill-authoring.md ("Plan files for write skills"): each change with its status (ready, blocked or no_change),
kind, before and after, the exact tool and payload, the undo, live impact, problems and warnings, and the batches
to confirm. A new redirect is created switched off and switched on as a separate change; any switch-on and any
delete is a batch of its own. Ready changes over the batch cap are deferred.

verify: --readback N=FILE is the search_redirects rule_id detail read back after writing change N (for a delete,
the read-back of the deleted rule). Reports each change as in_place, not_in_place or gone.

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
NOT_FOUND = re.compile(r"not.?found|404|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"account|site|catalog|domain|environment|workspace", re.I)  # a "not found" about these isn't the item
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
    if re.search(r"account", text, re.I):
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
            rule["sync_status"] = r.get("syncStatus", rule.get("sync_status"))
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
    running = {norm(x) for x in RULES["running_statuses"]}
    exps = []
    for e in records(path):
        status = norm(e.get("status") or e.get("experimentStatus"))
        if not status or status in running:  # a test with no status counts as running
            exps.append({"name": e.get("name"), "text": norm(json.dumps(e))})
    return exps


class Change:
    """Problems (blockers) and warnings for one requested change."""

    def __init__(self, n, raw):
        self.n, self.raw, self.problems, self.warnings = n, raw, [], []

    def add(self, severity, check, message):
        if severity == "blocker":
            self.problems.append({"check": check, "message": message})
        else:
            self.warnings.append({"check": check, "level": severity, "message": message})


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
        for other in sorted(rules.values(), key=lambda r: r["id"]):
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
        for k, v in sorted(caught, key=lambda kv: (-(kv[1]["revenue"] or 0), kv[0])):
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


def shown(fields):
    """Fields for before and after: dates as ISO text."""
    return {k: (iso(v) if k in ("started_at", "ended_at") else v) for k, v in fields.items()}


def describe(rid, rule, queries=None):
    if rid is None:
        return "new redirect " + ", ".join(f"'{q}'" for q in queries or [])
    keys = ", ".join(f"'{q}'" for q in (rule or {}).get("queries") or [])
    return f"redirect {rid}" + (f" ({keys})" if keys else "")


def change(c, kind, target, tool, payload, before, after, undo, live, note, **extra):
    return dict({"request": c.n, "reason": c.raw.get("reason"), "kind": kind, "target": target, "tool": tool,
                 "payload": payload, "before": before, "after": after, "undo": undo, "live_impact": live,
                 "impact_note": note, "problems": c.problems, "warnings": c.warnings}, **extra)


def recreate_steps(a, rule):
    """Undo of a delete: recreate switched off, then switch on (its own yes) only if it was on before."""
    args = dict(base_args(a), queries=rule.get("queries") or [], redirect_type=rule.get("redirect_type"), enabled=False)
    for k, v in (("destination_url", rule.get("url")), ("name", rule.get("name")), ("audience_id", rule.get("audience_id")),
                 ("started_at", rule.get("started_at")), ("ended_at", rule.get("ended_at"))):
        if v not in (None, ""):
            args[k] = v
    steps = [{"tool": "create_redirect", "payload": args,
              "note": "Recreated switched off, with a new ID and no edit history."}]
    if rule.get("enabled"):
        steps.append({"tool": "update_redirect",
                      "payload": dict(base_args(a), rule_id="<id returned by the recreate>", enabled=True),
                      "note": "Switches it back on: confirm it separately, as for any switch-on."})
    return steps


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
    target = describe(None, None, queries)
    out = [change(c, "create", target, "create_redirect", args, None,
                  shown({k: v for k, v in args.items() if k not in base_args(a)}),
                  [{"tool": "delete_redirect", "payload": dict(base_args(a), rule_id="<id returned by the create>"),
                    "note": "Deleting the new rule removes it completely."}],
                  "none", "None: created switched off.")]
    if raw.get("enabled") is not False:
        enable = Change(c.n, c.raw)  # its own change, confirmed on its own; the create holds the checks
        out.append(change(enable, "enable", target, "update_redirect",
                          dict(base_args(a), rule_id="<id returned by the create>", enabled=True),
                          {"enabled": False}, {"enabled": True},
                          [{"tool": "update_redirect",
                            "payload": dict(base_args(a), rule_id="<id returned by the create>", enabled=False)}],
                          "live", "Live for every shopper who searches " + ", ".join(f"'{q}'" for q in queries)
                          + " once Discovery syncs (seconds to minutes).", needs="create"))
    return out


FIELDS = ("queries", "redirect_type", "destination_url", "name", "enabled", "audience_id", "started_at", "ended_at")


def plan_update(c, raw, a, rules, revenue, exps, today_ms):
    rid = raw.get("rule_id")
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        c.add("blocker", "rule", "An update needs the redirect's numeric rule_id.")
        return [change(c, "update", f"redirect {rid}", "update_redirect", None, None, None, [], "none", None)]
    rule = rules.get(rid)
    target = describe(rid, rule)
    if not rule:
        c.add("blocker", "rule", f"Redirect {rid} isn't in the saved search_redirects results: fetch it first.")
        return [change(c, "update", target, "update_redirect", None, None, None, [], "none", None)]
    if not rule.get("detail"):
        c.add("blocker", "rule", f"Fetch redirect {rid} with search_redirects rule_id={rid} first: the list has no URL "
              "or match type, so the change and its undo can't be planned.")
        return [change(c, "update", target, "update_redirect", None, None, None, [], "none", None)]
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
        return [change(c, "update", target, "update_redirect", None, None, None, [], "none", None, no_change=True)]
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
    undo = [{"tool": "update_redirect", "payload": undo_args}] if set(undo_args) - set(base_args(a)) - {"rule_id"} else []
    extra = {}
    if manual:
        extra["undo_note"] = (f"update_redirect can't clear {', '.join(manual)} (an omitted field keeps its value); "
                              "undo that part in the Discovery dashboard.")
    switches_on = changed.get("enabled") is True and before.get("enabled") is not True
    kind = ("enable" if switches_on and set(changed) == {"enabled"} else
            "disable" if changed.get("enabled") is False and set(changed) == {"enabled"} else "update")
    if changed.get("enabled") is False:
        live, note = "live", "Off for all shoppers once Discovery syncs."
    elif after.get("enabled"):
        live, note = "live", "Live for every shopper who searches these keywords once Discovery syncs."
    else:
        live, note = "none", "None while the redirect is switched off."
    return [change(c, kind, target, "update_redirect", dict(base_args(a), rule_id=rid, **changed),
                   shown({k: before[k] for k in changed}), shown(changed), undo, live, note, switches_on=switches_on,
                   **extra)]


def plan_delete(c, raw, a, rules, exps):
    try:
        rid = int(raw.get("rule_id"))
    except (TypeError, ValueError):
        c.add("blocker", "rule", "A delete needs the redirect's numeric rule_id.")
        return [change(c, "delete", f"redirect {raw.get('rule_id')}", "delete_redirect", None, None, None, [], "none", None)]
    rule = rules.get(rid)
    target = describe(rid, rule)
    if not rule or not rule.get("detail"):
        c.add("blocker", "rule", f"Fetch redirect {rid} with search_redirects rule_id={rid} first: its full state is "
              "the only way to undo a delete.")
        return [change(c, "delete", target, "delete_redirect", None, None, None, [], "none", None)]
    check_experiments(c, rule.get("queries") or [], rid, rule, exps)
    if not rule.get("redirect_type"):
        c.add("blocker", "rule", f"Redirect {rid}'s match type is unknown, so it couldn't be recreated: don't delete it; "
              "switch it off instead.")
    c.add("warning", "permanent", "Deletes can't be undone in Discovery. The undo recreates the redirect switched off, "
          "with a new ID and no edit history. Switching it off is the reversible alternative.")
    before = {k: rule.get(k) for k in ("id", "name", "enabled", "queries", "redirect_type", "url", "audience_id")}
    before.update({"started_at": iso(rule.get("started_at")), "ended_at": iso(rule.get("ended_at"))})
    live = "live" if rule.get("enabled") else "none"
    note = ("Off for all shoppers once Discovery syncs, permanently." if rule.get("enabled") else
            "None: the redirect is switched off.")
    return [change(c, "delete", target, "delete_redirect", dict(base_args(a), rule_id=rid), before, None,
                   recreate_steps(a, rule), live, note)]


def day(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD")


def numbered_file(text):
    """N=FILE, split on the first "=": a plan change number and its read-back file."""
    n, sep, path = text.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 3=readback-3.json")
    try:
        return int(n), path
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a change number")


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({e}).")


def build_batches(changes):
    """One batch for the ordinary ready changes; each switch-on and each delete in a batch of its own."""
    ready = [ch for ch in changes if ch["status"] == "ready"]
    alone = [ch for ch in ready if ch["kind"] in ("delete", "enable") or ch.get("switches_on")]
    main = [ch["n"] for ch in ready if ch not in alone]
    ordered = sorted(alone, key=lambda ch: (ch["kind"] == "delete", ch["n"]))
    return ([main] if main else []) + [[ch["n"]] for ch in ordered]


ORDER = ("n", "request", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
         "impact_note", "problems", "warnings")


def cmd_plan(a):
    # Schedules are judged against midnight UTC of --today, or of today: the same reference either way.
    today = (a.today or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
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

    changes, deferred, ready_count, seen_ids = [], [], 0, set()
    for req, raw in enumerate(raw_changes, 1):
        c = Change(req, raw)
        action = raw.get("action")
        rid = raw.get("rule_id")
        if rid is not None:
            if rid in seen_ids:  # two changes to one redirect: the second's before and undo would be wrong
                c.add("blocker", "duplicate", f"Redirect {rid} already has a change in this plan. Plan one change "
                      "per redirect; to switch it off instead of deleting it, replace the delete, don't add to it.")
            seen_ids.add(rid)
        if action == "create":
            outs = plan_create(c, raw, a, rules, revenue, exps, today_ms)
        elif action == "update":
            outs = plan_update(c, raw, a, rules, revenue, exps, today_ms)
        elif action == "delete":
            outs = plan_delete(c, raw, a, rules, exps)
        else:
            c.add("blocker", "action", "action must be create, update or delete.")
            outs = [change(c, None, None, None, None, None, None, [], "none", None)]
        if c.problems:  # a blocked create has nothing to switch on
            outs = [o for o in outs if not o.get("needs")]
        for o in outs:
            o["status"] = "blocked" if c.problems else "no_change" if o.pop("no_change", False) else "ready"
        ready = [o for o in outs if o["status"] == "ready"]
        if ready and ready_count + len(ready) > cap:  # only ready changes count towards the cap
            deferred.append({"request": req, "action": action, "rule_id": raw.get("rule_id"),
                             "queries": raw.get("queries"), "reason": raw.get("reason")})
            continue
        ready_count += len(ready)
        changes.extend(outs)
    for n, ch in enumerate(changes, 1):
        ch["n"] = n
    for ch in changes:
        if ch["kind"] == "create":
            for u in ch["undo"]:
                u["payload"]["rule_id"] = f"<id returned by change {ch['n']}>"
        if ch.pop("needs", None) == "create":
            create_n = next(x["n"] for x in changes if x["request"] == ch["request"] and x["kind"] == "create")
            ch["after_change"] = create_n
            for payload in [ch["payload"]] + [u["payload"] for u in ch["undo"]]:
                payload["rule_id"] = f"<id returned by change {create_n}>"
    changes = [dict({k: ch.get(k) for k in ORDER}, **{k: v for k, v in ch.items() if k not in ORDER}) for ch in changes]
    return {"ok": True, "account": a.account, "environment": a.environment, "site_group_id": a.site_group_id,
            "today": today.strftime("%Y-%m-%d"), "batch_cap": cap, "changes": changes,
            "batches": build_batches(changes), "deferred": deferred,
            "counts": {s: sum(1 for ch in changes if ch["status"] == s) for s in ("ready", "blocked", "no_change")}}


def readback(path):
    """(redirects by ID, error text). A success:false read-back is returned as an error, not a failure."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            if re.search(r"account", str(d.get("error") or ""), re.I):
                # Never read an account error as "not found": the read-back went to the wrong account, so stop.
                fail(f"{path}: {ACCOUNT_LIST_ERROR} The read-back didn't reach the redirect, so nothing was checked.")
            return {}, tool_error(d.get("error"))
    return index_redirects([path]), None


def same(key, want, got):
    if key == "queries":
        return sorted(norm(q) for q in want or []) == sorted(norm(q) for q in got or [])
    if key in ("started_at", "ended_at"):
        return want == iso(got)
    return want == got


def cmd_verify(a):
    try:
        with open(a.plan, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{a.plan}: can't read it as JSON ({e}).")
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan file (no changes list). Use the file that redirect_plan.py plan wrote.")
    by_n = {ch.get("n"): ch for ch in plan["changes"] if isinstance(ch, dict) and isinstance(ch.get("n"), int)}
    files = dict(a.readback)
    results = []
    for n in sorted(files):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready" or not isinstance(ch.get("payload"), dict):
            fail(f"--readback {n}: the plan has no ready change {n}.")
        rules, err = readback(files[n])
        rid = ch["payload"].get("rule_id")
        if isinstance(rid, int):
            rule = rules.get(rid)
        else:  # a new redirect: the read-back is its detail, by the ID the create returned
            rule = next(iter(rules.values())) if len(rules) == 1 else None
        res = {"n": n, "kind": ch.get("kind"), "target": ch.get("target")}
        if ch.get("kind") == "delete":
            if err and not (NOT_FOUND.search(err) and not CONTEXT_ERROR.search(err)):
                # A rate limit, denied call or wrong site says nothing about the redirect: stop.
                fail(f"{files[n]}: {err} The read-back failed, so the delete can't be checked. Read it again.")
            res["state"] = "gone" if err or rule is None else "not_in_place"
        elif err or rule is None:
            res["state"] = "not_in_place"
            res["note"] = f"The read-back failed: {err}" if err else "The read-back doesn't hold this redirect."
        else:
            have = {"queries": rule.get("queries"), "redirect_type": rule.get("redirect_type"),
                    "destination_url": rule.get("url"), "name": rule.get("name"), "enabled": rule.get("enabled"),
                    "audience_id": rule.get("audience_id"), "started_at": rule.get("started_at"),
                    "ended_at": rule.get("ended_at")}
            want = ch.get("after") or {}
            if not rule.get("detail"):  # a list record has no URL, match type or audience
                want = {k: v for k, v in want.items() if k in ("queries", "enabled", "name")}
            bad = sorted(k for k in want if k in have and not same(k, want[k], have[k]))
            res["state"] = "not_in_place" if bad else "in_place"
            if bad:
                res["mismatches"] = [{"field": k, "planned": want[k],
                                      "found": iso(have[k]) if k in ("started_at", "ended_at") else have[k]} for k in bad]
            res["sync_status"] = rule.get("sync_status")
            if not isinstance(rid, int):
                res["rule_id"] = rule.get("id")
        results.append(res)
    unchecked = sorted(n for n, ch in by_n.items() if ch.get("status") == "ready" and n not in files)
    return {"ok": True, "results": results, "not_checked": unchecked,
            "note": "A delete counts as gone only with a read-back; the changes in not_checked have none."}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # keywords can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="turn the requested changes into a plan")
    p.add_argument("--changes", required=True, help="JSON list of changes (references/change-format.md)")
    p.add_argument("--redirects", action="append", required=True, help="saved search_redirects list page or detail (repeat)")
    p.add_argument("--queries", action="append", default=[], help="saved get_discovery_query_performance table (repeat)")
    p.add_argument("--experiments", help="saved search_discovery_experiments result")
    p.add_argument("--account", required=True, help="the Discovery account name the user confirmed")
    p.add_argument("--environment", required=True, choices=["staging", "production"])
    p.add_argument("--site-group-id", help="site group ID or site name, if the account has sites")
    p.add_argument("--today", type=day, help="YYYY-MM-DD to judge schedules against (default: today, UTC)")
    p.add_argument("--out", help="also write the plan (with every undo) to this file")
    v = sub.add_parser("verify", help="check the read-backs after writing")
    v.add_argument("--plan", required=True, help="the plan file from the plan step")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the search_redirects rule_id result read back after writing change N (repeat)")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = cmd_plan(a) if a.cmd == "plan" else cmd_verify(a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    write_out(a.out, text)
    print(text)


if __name__ == "__main__":
    main()
