#!/usr/bin/env python3
"""Build the change plan for closing a Bloomreach Discovery A/B test. It never writes anything itself.

Usage:
  python3 close_plan.py --experiment experiment.json [--report report.json] [--rule rule_2221685.json ...]
         [--keep "<bucket name or id>"] [--override] [--account <account>] [--today 2026-11-03] [--out plan.json]

--experiment  saved search_discovery_experiments result fetched with experiment_id (it has successMetric,
              winnerBucketId and environment_used).
--report      saved get_discovery_experiment_report result. Needed to ship a change; optional to keep the control.
--rule        saved get_ranking_rule result for a bucket's rule (repeat per rule): the before state.
--keep        the bucket that should serve everyone after the test. Default: the script's recommendation
              (the conclusive winner if there is one, otherwise the control).
--override    the user has seen the warnings and still wants to ship a change the evidence doesn't support.
--account     the account name to put in the payloads (default "<account>").
--today       the date to count a running test's days to (default: today in UTC).

Prints JSON: the experiment and its buckets with the before state of each rule; the evidence gate (metric,
confidence, days, guardrails, split); the decision and whether it ships a change; whether the plan is refused and
why; and the steps in order, each with its tool, exact payload, live impact, whether it can be undone, how to check
it, and the undo. Conditional steps run only if the read-back after ending shows they're needed.

Thresholds are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# The thresholds live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
METRIC_WORDS = {"cr": ("cr", "conversion"), "atc_rate": ("atc", "add-to-cart", "add to cart"),
                "aov": ("aov", "average order"), "rpv": ("rpv", "revenue per visit")}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error safe to repeat. An unknown account_name makes some Discovery tools list every
    account the user can access, so an account error that looks like a list is replaced, never echoed."""
    text = str(err or "no error text")
    if "account" in text.lower() and text.count(",") >= 3:
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


def load(path):
    """The data object of a saved Loomi Connect result, unwrapping {"result": ...} and data.data."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    env = None
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict):
            if d.get("success") is False:
                fail(f"{path}: {tool_error(d.get('error'))} This step couldn't run; don't treat it as 'nothing found'.")
            env = env or d.get("environment_used")
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        fail(f"{path}: expected an object in 'data'.")
    return data, env


def day_arg(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}")


def ms_date(value, path, field):
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        fail(f"{path}: {field} isn't a Unix time in milliseconds.")


def metric_key(text):
    t = str(text or "").strip().lower()
    for key, words in METRIC_WORDS.items():
        if t == key or any(t.startswith(w) for w in words):
            return key
    return None


def num(value, path, field):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        fail(f"{path}: {field} isn't a number.")


def read_buckets(exp, path):
    out = []
    for b in exp.get("buckets") or []:
        if not isinstance(b, dict) or b.get("id") in (None, ""):
            fail(f"{path}: a bucket has no id.")
        info = b.get("ruleIdentifierInfo") or None
        rule = None
        if info:
            if info.get("id") in (None, ""):
                fail(f"{path}: bucket {b.get('bucketName')!r} has ruleIdentifierInfo without an id.")
            rule = {"id": info.get("id"), "type": info.get("ruleType") or "ranking",
                    "queries": [{"query": q.get("query"), "queryType": q.get("queryType")} for q in info.get("query") or []]}
        out.append({"id": b["id"], "name": b.get("bucketName"), "control": bool(b.get("control")),
                    "traffic_pct": num(b.get("trafficPercentage"), path, "buckets[].trafficPercentage"), "rule": rule})
    if len(out) < 2:
        fail(f"{path}: an experiment needs at least two buckets.")
    if sum(1 for b in out if b["control"]) != 1:
        fail(f"{path}: expected exactly one control bucket.")
    return out


def read_report(path, buckets):
    data, _ = load(path)
    rows = ((data.get("overalldata") or {}).get("buckets")) or {}
    if not isinstance(rows, dict) or not rows:
        fail(f"{path}: no overalldata.buckets in the report.")
    by_name = {}
    for b in buckets:
        r = rows.get(b["name"])
        if not isinstance(r, dict):
            fail(f"{path}: the report has no row for bucket {b['name']!r}. Fetch it with the experiment's exact bucket names.")
        by_name[b["name"]] = {
            "visits": int(num(r.get("visits"), path, "visits") or 0),
            "values": {m: num(r.get(m), path, m) for m in RULES["metrics"]},
            "lift": {m: num((r.get("lift") or {}).get(m), path, f"lift.{m}") for m in RULES["metrics"]},
            "confidence": {m: num((r.get("confidenceValues") or {}).get(m), path, f"confidenceValues.{m}")
                           for m in RULES["metrics"]},
        }
    return by_name


def read_rules(paths):
    out = {}
    for p in paths:
        data, _ = load(p)
        if data.get("id") in (None, ""):
            fail(f"{p}: not a get_ranking_rule result (no id).")
        out[str(data["id"])] = {"enabled": data.get("enabled"), "is_live": data.get("isLive"),
                                "sync_status": data.get("syncStatus"), "audiences": len(data.get("audiences") or []),
                                "queries": [q.get("query") for q in data.get("queries") or []]}
    return out


def evidence(buckets, report, metric, keep, days, warnings):
    """The gate for shipping `keep`. Returns the reasons it fails (empty when the evidence supports it)."""
    reasons = []
    if report is None:
        return ["No experiment report was given, so there's no evidence for the change."]
    total = sum(r["visits"] for r in report.values())
    if total <= 0:
        return ["The report has 0 visits in every bucket: no data, not 'no difference'. Check the dates and session type."]
    conf = {b["name"]: report[b["name"]]["confidence"][metric] for b in buckets}
    if all(not c for c in conf.values()):
        reasons.append(f"Confidence wasn't calculated on {metric} (all values are 0 or missing): too little data.")
    elif (conf[keep["name"]] or 0) < RULES["min_confidence"]:
        reasons.append(f"{keep['name']} is {conf[keep['name']] or 0:.0%} likely best on {metric}, under "
                       f"min_confidence ({RULES['min_confidence']:.0%}): the result is inconclusive.")
    if days < RULES["min_days"]:
        reasons.append(f"The test has run {days} days, under min_days ({RULES['min_days']}).")
    for m in RULES["metrics"]:
        if m == metric:
            continue
        lift = report[keep["name"]]["lift"][m]
        rival = max(((b["name"], report[b["name"]]["confidence"][m] or 0) for b in buckets if b["name"] != keep["name"]),
                    key=lambda t: t[1])
        if lift is not None and lift < 0 and rival[1] >= RULES["guardrail_confidence"]:
            reasons.append(f"Guardrail {m}: {keep['name']} is {lift:+.1%} and {rival[0]} is {rival[1]:.0%} likely best.")
    for b in buckets:
        share = 100.0 * report[b["name"]]["visits"] / total
        if b["traffic_pct"] is not None and abs(share - b["traffic_pct"]) > RULES["max_split_imbalance_pct"]:
            warnings.append(f"{b['name']} got {share:.1f}% of visits against a planned {b['traffic_pct']:.0f}%: "
                            "traffic allocation may be broken; treat the result with caution.")
    return reasons


def recommend(buckets, report, metric, days):
    """The conclusive winner if one passes the gate, otherwise the control."""
    control = next(b for b in buckets if b["control"])
    if report is None:
        return control
    for b in buckets:
        if not b["control"] and not evidence(buckets, report, metric, b, days, []):
            return b
    return control


def payload(account, env, exp_id, **extra):
    p = {"account_name": account, "experiment_id": exp_id}
    if env:
        p["environment"] = env
    p.update(extra)
    return p


def build_steps(exp, buckets, keep, rules_before, account, env, ships_change):
    status = str(exp.get("experimentStatus") or "").upper()
    steps = []
    if ships_change:
        target = (f"rule {keep['rule']['id']}" if keep["rule"] else
                  f"removing rule {next(b['rule']['id'] for b in buckets if b['control'])} (default behaviour)")
        steps.append({"step": "change_qa", "write": False,
                      "what": f"Run the discovery-change-qa checks on {target} for the test's scope. Stop on NO-GO; "
                              "show the warnings on GO WITH CAUTION and ask whether to continue."})
    if status == "RUNNING":
        extra = {"winner_bucket_id": keep["id"]} if keep["rule"] else {}
        impact = (f"LIVE at once: {keep['name']} (rule {keep['rule']['id']}) serves 100% of traffic for the test's scope; "
                  "every other bucket's rule is disabled." if keep["rule"] else
                  "LIVE at once: every bucket's rule is disabled and traffic returns to default behaviour "
                  f"({keep['name']}). No winner is recorded.")
        steps.append({"step": "end", "write": True, "tool": "end_discovery_experiment",
                      "payload": payload(account, env, exp.get("id"), **extra), "live_impact": impact,
                      "undo": None, "irreversible": "Ending can't be undone and a COMPLETED test can't be restarted.",
                      "verify": "search_discovery_experiments with experiment_id: experimentStatus is COMPLETED"
                                + (f" and winnerBucketId is {keep['id']}." if keep["rule"] else ".")})
    elif status == "COMPLETED":
        steps.append({"step": "end", "write": False, "what": "Already COMPLETED: nothing to end. The rule checks below "
                      "still apply."})
    for b in buckets:
        if not b["rule"]:
            continue
        rid, kept = b["rule"]["id"], b["id"] == keep["id"]
        tool = "update_ranking_rule" if b["rule"]["type"] == "ranking" else None
        before = rules_before.get(str(rid))
        check = {"step": "read_back", "write": False, "rule_id": rid, "bucket": b["name"],
                 "what": f"get_ranking_rule {rid}: expect enabled {'true' if kept else 'false'}"
                         + (" and syncStatus SUCCESS." if kept else ".")}
        if b["rule"]["type"] != "ranking":
            check["what"] = (f"{b['rule']['type']} rule {rid}: read it back with its own read tool (search_redirects with "
                             f"rule_id for a redirect) and expect enabled {'true' if kept else 'false'}.")
        steps.append(check)
        fix = {"step": "enable_winner" if kept else "disable_leftover", "write": True, "conditional": True,
               "when": f"only if the read-back shows rule {rid} {'disabled' if kept else 'still enabled'}",
               "rule_id": rid, "bucket": b["name"], "before": before}
        if tool:
            fix.update(tool=tool, payload={"account_name": account, "rule_id": rid, "enabled": kept, **({"environment": env} if env else {})},
                       live_impact=(f"LIVE: rule {rid} applies to every shopper in its scope." if kept else
                                    f"LIVE: rule {rid} stops applying."),
                       undo={"tool": tool, "payload": {"account_name": account, "rule_id": rid, "enabled": not kept,
                                                       **({"environment": env} if env else {})}},
                       irreversible=None)
        else:
            fix.update(tool=None, live_impact="This skill doesn't write non-ranking rules: give the user the change to make "
                       "in the Discovery dashboard.", undo=None, irreversible=None)
        steps.append(fix)
    if status in ("RUNNING", "COMPLETED"):
        steps.append({"step": "archive", "write": True, "optional": True, "tool": "archive_discovery_experiment",
                      "payload": payload(account, env, exp.get("id")), "live_impact": "None: it only hides the "
                      "experiment from the dashboard's default view.", "undo": None,
                      "irreversible": "Loomi Connect has no tool to unarchive; the dashboard may allow it.",
                      "verify": "search_discovery_experiments with experiment_id: experimentStatus is ARCHIVED."})
    return steps


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiment", required=True, help="saved search_discovery_experiments result for one experiment")
    ap.add_argument("--report", help="saved get_discovery_experiment_report result")
    ap.add_argument("--rule", action="append", default=[], help="saved get_ranking_rule result (repeat per rule)")
    ap.add_argument("--keep", help="bucket name or id to keep (default: the recommendation)")
    ap.add_argument("--override", action="store_true", help="ship the change despite the evidence warnings")
    ap.add_argument("--account", default="<account>", help="account name for the payloads")
    ap.add_argument("--today", type=day_arg, help="date to count a running test to (default: today in UTC)")
    ap.add_argument("--out", help="also write the plan to this file")
    a = ap.parse_args()

    exp, env = load(a.experiment)
    if exp.get("id") in (None, "") or "buckets" not in exp:
        fail(f"{a.experiment}: not one experiment's detail. Fetch it with search_discovery_experiments and experiment_id.")
    status = str(exp.get("experimentStatus") or "").upper()
    buckets = read_buckets(exp, a.experiment)
    report = read_report(a.report, buckets) if a.report else None
    rules_before = read_rules(a.rule)
    today = a.today or datetime.now(timezone.utc).date()
    start = ms_date(exp.get("startedAt"), a.experiment, "startedAt")
    end = ms_date(exp.get("endedAt"), a.experiment, "endedAt")
    days = ((end or today) - start).days if start else 0
    warnings = []
    metric = metric_key(exp.get("successMetric"))
    if not metric:
        metric = RULES["default_metric"]
        warnings.append(f"The experiment has no success metric; using default_metric ({metric}).")

    out = {"ok": True, "experiment": {"id": exp.get("id"), "name": exp.get("experimentName"), "status": status,
                                      "environment": env, "success_metric": exp.get("successMetric"), "metric": metric,
                                      "started": start.isoformat() if start else None,
                                      "ended": end.isoformat() if end else None, "days": days,
                                      "declared_winner_bucket_id": exp.get("winnerBucketId")},
           "buckets": [dict(b, rule_before=rules_before.get(str(b["rule"]["id"])) if b["rule"] else None,
                            result=report.get(b["name"]) if report else None) for b in buckets]}
    if status in ("DRAFT", "ARCHIVED"):
        out.update(refused=True, refusal_reasons=[
            "A DRAFT never ran: there's nothing to end. Delete or edit it in the Discovery dashboard." if status == "DRAFT"
            else "Already ARCHIVED: there's nothing left to close."], steps=[], warnings=warnings)
        return emit(out, a.out)

    recommended = recommend(buckets, report, metric, days)
    if a.keep:
        keep = next((b for b in buckets if str(b["id"]) == a.keep or b["name"] == a.keep), None)
        if keep is None:
            fail(f"--keep {a.keep!r} matches no bucket name or id in {a.experiment}.")
    else:
        keep = recommended
    control = next(b for b in buckets if b["control"])
    ships_change = not keep["control"]
    reasons = evidence(buckets, report, metric, keep, days, warnings) if ships_change else []
    if not ships_change and report is not None:
        better = [b["name"] for b in buckets if not b["control"]
                  and (report[b["name"]]["confidence"][metric] or 0) >= RULES["min_confidence"]]
        if better:
            warnings.append(f"Keeping the control although {', '.join(better)} is at least "
                            f"{RULES['min_confidence']:.0%} likely best on {metric}.")
    if status == "COMPLETED" and exp.get("winnerBucketId") not in (None, keep["id"]) and keep["rule"]:
        warnings.append("The test already ended with a different winner; ending can't be redone, so the kept rule can "
                        "only be switched on with update_ranking_rule (its own yes).")
    refused = bool(reasons) and not a.override
    if reasons and a.override:
        warnings += [f"Overridden: {r}" for r in reasons]
    out.update(
        recommended_bucket={"id": recommended["id"], "name": recommended["name"]},
        decision={"keep_bucket": keep["name"], "keep_bucket_id": keep["id"], "keep_rule_id": (keep["rule"] or {}).get("id"),
                  "control_bucket": control["name"], "ships_change": ships_change,
                  "follows_recommendation": keep["id"] == recommended["id"]},
        gate={"metric": metric, "min_confidence": RULES["min_confidence"], "min_days": RULES["min_days"],
              "days": days, "reasons": reasons},
        refused=refused, refusal_reasons=reasons if refused else [], override_used=bool(reasons and a.override),
        warnings=warnings,
        steps=[] if refused else build_steps(exp, buckets, keep, rules_before, a.account, env, ships_change))
    emit(out, a.out)


def emit(out, path):
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if path:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
