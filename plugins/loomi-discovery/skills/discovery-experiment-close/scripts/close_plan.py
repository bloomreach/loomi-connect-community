#!/usr/bin/env python3
"""Build and check the plan for closing a Bloomreach Discovery A/B test. It never writes anything itself.

Usage:
  python3 close_plan.py plan --experiment experiment.json --account <account> [--environment staging]
         [--site-group-id <id>] [--report report.json] [--rule <rule id>=rule.json ...] [--keep "<bucket>"]
         [--override] [--today 2026-11-03] [--out plan.json]
  python3 close_plan.py verify --plan plan.json [--experiment experiment_after.json] [--rule <rule id>=rule.json ...]
         [--out verify.json]

plan:
  --experiment     saved search_discovery_experiments result fetched with experiment_id (any status): it has the
                   buckets, successMetric, winnerBucketId and environment_used.
  --account        the account name for the payloads (required).
  --environment    production or staging. Required unless the experiment carries environment_used; if both are
                   given they must match.
  --site-group-id  the site, when the account has sites: copied into every payload.
  --report         saved get_discovery_experiment_report result. Needed to ship a change.
  --rule           <rule id>=<saved get_ranking_rule result> for a bucket's rule (repeat per rule): the before state.
  --keep           the bucket to keep (name or id). Default: the recommendation (the conclusive winner, else the control).
  --override       the user has seen the warnings and still wants to ship a change the evidence doesn't support.

verify:
  --plan           the plan file written by `plan --out`.
  --experiment     the experiment fetched again after a write.
  --rule           <rule id>=<saved get_ranking_rule result> read back after ending (repeat per rule). A not-found
                   response counts as gone.

The plan follows "Plan files for write skills" in docs/skill-authoring.md: `changes` are the steps in order (end,
enable/disable a rule only if the read-back shows it's needed, archive), each a batch of its own, plus the decision,
the evidence gate and warnings. Refused changes are `blocked` with the reasons in `problems`.

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
ENVIRONMENTS = ("production", "staging")
NOT_FOUND = ("not found", "not_found", "404", "does not exist", "doesn't exist", "no such")
CONTEXT_ERROR = re.compile(r"account|site|catalog|domain|environment|workspace", re.I)  # a "not found" about these isn't the item
IRREVERSIBLE = {"end": "Ending can't be undone and a COMPLETED test can't be restarted.",
                "archive": "Loomi Connect has no tool to unarchive; the dashboard may allow it."}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error safe to repeat. An unknown account_name makes some Discovery tools list every account
    the user can access, so any error about an account is replaced, never echoed."""
    text = str(err or "no error text")
    if "account" in text.lower():
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def errors_in(doc):
    """The error text of a success:false response (top level or under "result"), or None."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return str(d.get("error") or "no error text")
    return None


def unwrap(doc, path):
    """The data object of a saved Loomi Connect result, unwrapping {"result": ...} and data.data, plus the
    environment the call used."""
    env = None
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict):
            env = env or d.get("environment_used")
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        fail(f"{path}: expected an object in 'data'.")
    return data, env


def load(path):
    doc = read_json(path)
    err = errors_in(doc)
    if err is not None:
        fail(f"{path}: {tool_error(err)} This step couldn't run; don't treat it as 'nothing found'.")
    return unwrap(doc, path)


def day_arg(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}")


def rule_arg(text):
    """<rule id>=<file>, split on the first "="."""
    rid, sep, path = text.partition("=")
    if not sep or not rid.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"use <rule id>=<file>: {text!r}")
    return rid.strip(), path.strip()


def env_arg(text):
    t = text.strip().lower()
    if t not in ENVIRONMENTS:
        raise argparse.ArgumentTypeError(f"environment must be production or staging: {text!r}")
    return t


def site_arg(text):
    t = text.strip()
    if not t:
        raise argparse.ArgumentTypeError("site_group_id is empty")
    return int(t) if t.isdigit() else t


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


def rule_state(data):
    return {"enabled": data.get("enabled"), "is_live": data.get("isLive"), "sync_status": data.get("syncStatus"),
            "audiences": len(data.get("audiences") or []), "queries": [q.get("query") for q in data.get("queries") or []]}


def read_rules(pairs):
    out = {}
    for rid, path in pairs:
        data, _ = load(path)
        if data.get("id") in (None, ""):
            fail(f"{path}: not a get_ranking_rule result (no id).")
        if str(data["id"]) != rid:
            fail(f"{path}: holds rule {data['id']}, not rule {rid}.")
        out[rid] = rule_state(data)
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


def change(n, kind, target, tool, payload, before, after, undo, live_impact, impact, problems=None, warnings=None,
           **extra):
    c = {"n": n, "status": "blocked" if problems else "ready", "kind": kind, "target": target, "tool": tool,
         "payload": payload, "before": before, "after": after, "undo": undo, "live_impact": live_impact,
         "impact": impact, "problems": list(problems or []), "warnings": list(warnings or [])}
    c.update(extra)
    return c


def build_changes(exp, buckets, keep, rules_before, ctx, refusal):
    """The steps in order. `refusal` (the evidence reasons, when not overridden) blocks every write."""
    status = str(exp.get("experimentStatus") or "").upper()
    base = {k: v for k, v in (("account_name", ctx["account"]), ("environment", ctx["environment"]),
                               ("site_group_id", ctx["site_group_id"])) if v is not None}
    exp_id = exp.get("id")
    changes = []

    if status == "RUNNING":
        payload = dict(base, experiment_id=exp_id, **({"winner_bucket_id": keep["id"]} if keep["rule"] else {}))
        impact = (f"Live at once: {keep['name']} (rule {keep['rule']['id']}) serves 100% of traffic for the test's scope; "
                  "every other bucket's rule is disabled." if keep["rule"] else
                  "Live at once: every bucket's rule is disabled and traffic returns to default behaviour "
                  f"({keep['name']}). No winner is recorded.")
        changes.append(change(len(changes) + 1, "end", f"experiment {exp_id}", "end_discovery_experiment", payload,
                              {"experimentStatus": status, "winnerBucketId": exp.get("winnerBucketId")},
                              {"experimentStatus": "COMPLETED", "winnerBucketId": keep["id"] if keep["rule"] else None},
                              [], "live", impact, refusal, [IRREVERSIBLE["end"]]))
    elif status == "COMPLETED":
        c = change(len(changes) + 1, "end", f"experiment {exp_id}", None, None,
                   {"experimentStatus": status, "winnerBucketId": exp.get("winnerBucketId")},
                   {"experimentStatus": status, "winnerBucketId": exp.get("winnerBucketId")}, [], "none",
                   "Already COMPLETED: nothing to end. The rule checks below still apply.")
        c["status"] = "no_change"
        changes.append(c)

    for b in buckets:  # the experiment's own bucket order
        if not b["rule"]:
            continue
        rid, kept = b["rule"]["id"], b["id"] == keep["id"]
        kind = "enable" if kept else "disable"
        before = rules_before.get(str(rid))
        problems = list(refusal)
        if b["rule"]["type"] != "ranking":
            problems.append(f"{b['rule']['type']} rule {rid}: this skill doesn't write non-ranking rules. If the "
                            "read-back shows it in the wrong state, give the user the change to make in the Discovery "
                            "dashboard (read it back with search_redirects and rule_id for a redirect).")
            tool = payload = None
            undo = []
        else:
            tool = "update_ranking_rule"
            payload = dict(base, rule_id=rid, enabled=kept)
            undo = [{"tool": tool, "payload": dict(base, rule_id=rid, enabled=not kept)}]
        changes.append(change(
            len(changes) + 1, kind, f"rule {rid} ({b['name']})", tool, payload, before, {"enabled": kept}, undo, "live",
            (f"Live: rule {rid} applies to every shopper in its scope." if kept else f"Live: rule {rid} stops applying."),
            problems, [], conditional=True,
            when=f"only if the read-back after ending shows rule {rid} {'disabled' if kept else 'still enabled'}"))

    if status in ("RUNNING", "COMPLETED"):
        changes.append(change(
            len(changes) + 1, "archive", f"experiment {exp_id}", "archive_discovery_experiment",
            dict(base, experiment_id=exp_id), {"experimentStatus": "COMPLETED"}, {"experimentStatus": "ARCHIVED"}, [],
            "none", "None on shoppers: it only hides the experiment from the dashboard's default view.",
            refusal, [IRREVERSIBLE["archive"]], optional=True))
    return changes


def resolve_environment(given, from_exp, path):
    from_exp = str(from_exp).strip().lower() if from_exp else None
    if from_exp and from_exp not in ENVIRONMENTS:
        fail(f"{path}: environment_used is {from_exp!r}, not production or staging.")
    if given and from_exp and given != from_exp:
        fail(f"--environment is {given} but the experiment was fetched from {from_exp}. Use the experiment's environment.")
    env = given or from_exp
    if not env:
        fail(f"{path} doesn't say which environment the experiment is in (no environment_used). Pass --environment "
             "production or staging; it's never assumed.")
    return env


def emit(out, path):
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write the output file ({e}).")
    print(text)


def cmd_plan(a):
    exp, env_used = load(a.experiment)
    if exp.get("id") in (None, "") or "buckets" not in exp:
        fail(f"{a.experiment}: not one experiment's detail. Fetch it with search_discovery_experiments and experiment_id.")
    env = resolve_environment(a.environment, env_used, a.experiment)
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

    out = {"ok": True, "account": a.account, "environment": env, "site_group_id": a.site_group_id,
           "experiment": {"id": exp.get("id"), "name": exp.get("experimentName"), "status": status,
                          "success_metric": exp.get("successMetric"), "metric": metric,
                          "started": start.isoformat() if start else None, "ended": end.isoformat() if end else None,
                          "days": days, "declared_winner_bucket_id": exp.get("winnerBucketId")},
           "buckets": [dict(b, rule_before=rules_before.get(str(b["rule"]["id"])) if b["rule"] else None,
                            result=report.get(b["name"]) if report else None) for b in buckets]}
    if status in ("DRAFT", "ARCHIVED"):
        out.update(refused=True, refusal_reasons=[
            "A DRAFT never ran: there's nothing to end. Delete or edit it in the Discovery dashboard." if status == "DRAFT"
            else "Already ARCHIVED: there's nothing left to close."], checks_before=[], warnings=warnings,
            changes=[], batches=[])
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
    checks = []
    if ships_change:
        target = (f"rule {keep['rule']['id']}" if keep["rule"] else
                  f"removing rule {control['rule']['id']} (default behaviour)" if control["rule"] else "default behaviour")
        checks.append(f"Run the discovery-change-qa checks on {target} for the test's scope. Stop on NO-GO; show the "
                      "warnings on GO WITH CAUTION and ask whether to continue.")
    ctx = {"account": a.account, "environment": env, "site_group_id": a.site_group_id}
    changes = build_changes(exp, buckets, keep, rules_before, ctx, reasons if refused else [])
    out.update(
        recommended_bucket={"id": recommended["id"], "name": recommended["name"]},
        decision={"keep_bucket": keep["name"], "keep_bucket_id": keep["id"], "keep_rule_id": (keep["rule"] or {}).get("id"),
                  "control_bucket": control["name"], "ships_change": ships_change,
                  "follows_recommendation": keep["id"] == recommended["id"]},
        gate={"metric": metric, "min_confidence": RULES["min_confidence"], "min_days": RULES["min_days"],
              "days": days, "reasons": reasons},
        refused=refused, refusal_reasons=reasons if refused else [], override_used=bool(reasons and a.override),
        warnings=warnings, checks_before=checks, changes=changes,
        batches=[[c["n"]] for c in changes if c["status"] == "ready"])
    emit(out, a.out)


def read_plan(path):
    plan = read_json(path)
    if not isinstance(plan, dict) or plan.get("ok") is not True or not isinstance(plan.get("changes"), list):
        fail(f"{path}: not a plan written by close_plan.py plan --out.")
    for c in plan["changes"]:
        if not isinstance(c, dict) or not all(k in c for k in ("n", "kind", "target", "status", "after")):
            fail(f"{path}: a change is missing n, kind, target, status or after.")
    return plan


def readback(path):
    """(data, None) for a saved read-back, or (None, "gone") when the response says the item wasn't found."""
    doc = read_json(path)
    err = errors_in(doc)
    if err is not None:
        # "Account not found" is an account error, not a missing item: stop rather than report "gone".
        if not CONTEXT_ERROR.search(err) and any(w in err.lower() for w in NOT_FOUND):
            return None, "gone"
        fail(f"{path}: {tool_error(err)} The read-back couldn't run; don't treat it as checked.")
    data, _ = unwrap(doc, path)
    return data, None


def cmd_verify(a):
    plan = read_plan(a.plan)
    exp = None
    if a.experiment:
        exp, gone = readback(a.experiment)
        if gone:
            exp = {"experimentStatus": "GONE"}
    rules = {}
    for rid, path in a.rule:
        data, gone = readback(path)
        if data is not None and str(data.get("id")) != rid:
            fail(f"{path}: holds rule {data.get('id')}, not rule {rid}.")
        rules[rid] = "gone" if gone else data
    results = []
    for c in plan["changes"]:
        r = {"n": c["n"], "kind": c["kind"], "target": c["target"], "planned_status": c["status"]}
        if c["kind"] in ("end", "archive"):
            if exp is None:
                r.update(result="not_checked", detail="Pass the experiment fetched again with --experiment.")
            elif exp.get("experimentStatus") == "GONE":
                r.update(result="gone", detail="The experiment wasn't found.")
            else:
                st = str(exp.get("experimentStatus") or "").upper()
                want = c["after"].get("experimentStatus")
                ok = st == want or (want == "COMPLETED" and st == "ARCHIVED")
                if ok and c["kind"] == "end" and c["after"].get("winnerBucketId") is not None:
                    ok = exp.get("winnerBucketId") == c["after"]["winnerBucketId"]
                r.update(result="in_place" if ok else "not_in_place",
                         detail=f"experimentStatus {st}, winnerBucketId {exp.get('winnerBucketId')}")
        else:
            rid = c["target"].split()[1]
            got = rules.get(rid)
            if got is None:
                r.update(result="not_checked", detail=f"Pass rule {rid} read back after ending with --rule {rid}=<file>.")
            elif got == "gone":
                r.update(result="gone", detail=f"Rule {rid} wasn't found.")
            else:
                ok = got.get("enabled") == c["after"]["enabled"]
                r.update(result="in_place" if ok else "not_in_place", state=rule_state(got),
                         action=("none: already in the right state" if ok else
                                 "make this change (its own yes)" if c.get("conditional") and c["status"] == "ready"
                                 else "give the user the change to make in the dashboard"))
                if ok and c["after"]["enabled"] and got.get("syncStatus") not in (None, "SUCCESS"):
                    r["detail"] = f"syncStatus is {got.get('syncStatus')}: read it again in a minute."
        results.append(r)
    emit({"ok": True, "plan": a.plan, "results": results,
          "all_in_place": all(x["result"] == "in_place" for x in results)}, a.out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="build the plan for closing one experiment")
    p.add_argument("--experiment", required=True, help="saved search_discovery_experiments result for one experiment")
    p.add_argument("--account", required=True, help="account name for the payloads")
    p.add_argument("--environment", type=env_arg, help="production or staging (required unless the experiment says)")
    p.add_argument("--site-group-id", type=site_arg, help="site group ID, copied into every payload")
    p.add_argument("--report", help="saved get_discovery_experiment_report result")
    p.add_argument("--rule", type=rule_arg, action="append", default=[],
                   help="<rule id>=<saved get_ranking_rule result> (repeat per rule)")
    p.add_argument("--keep", help="bucket name or id to keep (default: the recommendation)")
    p.add_argument("--override", action="store_true", help="ship the change despite the evidence warnings")
    p.add_argument("--today", type=day_arg, help="date to count a running test to (default: today in UTC)")
    p.add_argument("--out", help="also write the plan to this file")
    v = sub.add_parser("verify", help="check the read-backs against the plan")
    v.add_argument("--plan", required=True, help="plan file from `plan --out`")
    v.add_argument("--experiment", help="the experiment fetched again after a write")
    v.add_argument("--rule", type=rule_arg, action="append", default=[],
                   help="<rule id>=<rule read back after ending> (repeat per rule)")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    cmd_plan(a) if a.cmd == "plan" else cmd_verify(a)


if __name__ == "__main__":
    main()
