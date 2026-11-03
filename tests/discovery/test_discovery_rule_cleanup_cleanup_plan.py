"""Tests for discovery-rule-cleanup's cleanup_plan.py. The fixtures are synthetic rule details."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-rule-cleanup"
SCRIPT = SKILL / "scripts/cleanup_plan.py"
FX = ROOT / "tests/fixtures/discovery/rule_cleanup"
IDS = range(101, 114)
CHANGE_KEYS = {"n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings"}


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def plan(*extra, request=FX / "request.json", ids=IDS, environment="staging"):
    rules = [a for i in ids for a in ("--rule", f"{i}={FX / f'rule_{i}.json'}")]
    r = run("plan", "--request", request, *rules, "--today", "2026-11-04", "--account", "demo_account",
            "--environment", environment, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def ready(p):
    return {e["rule_id"]: e for e in p["changes"] if e["status"] == "ready"}


def blocked(p):
    return {e["rule_id"]: e for e in p["changes"] if e["status"] == "blocked"}


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = plan("--experiments", FX / "experiments.json")

    def test_shared_plan_shape(self):
        self.assertEqual((self.p["account"], self.p["environment"], self.p["site_group_id"]),
                         ("demo_account", "staging", None))
        for e in self.p["changes"]:
            self.assertTrue(CHANGE_KEYS <= set(e), e["n"])
            self.assertIn(e["status"], ("ready", "blocked", "no_change"))
            self.assertIn(e["live_impact"], ("none", "live"))
            self.assertIsInstance(e["undo"], list)
        self.assertEqual([e["n"] for e in self.p["changes"]], list(range(1, len(self.p["changes"]) + 1)))

    def test_every_ready_change_has_before_after_payload_and_undo(self):
        for e in ready(self.p).values():
            for key in ("before", "tool", "payload", "qa"):
                self.assertTrue(e.get(key), (e["rule_id"], key))
            self.assertTrue(e["undo"] or e["undo_note"], e["rule_id"])
            self.assertEqual(e["payload"]["environment"], "staging")
            self.assertEqual(e["payload"]["account_name"], "demo_account")
            self.assertEqual(e["live_impact"], "live")

    def test_disable(self):
        e = ready(self.p)["101"]
        self.assertEqual((e["kind"], e["tool"], e["payload"]["enabled"]), ("disable", "update_ranking_rule", False))
        self.assertEqual(e["undo"], [{"tool": "update_ranking_rule", "payload": {
            "rule_id": 101, "environment": "staging", "account_name": "demo_account", "enabled": True}}])
        self.assertEqual(e["after"]["enabled"], False)

    def test_delete_only_when_disabled_and_expired(self):
        deletes = {rid: e for rid, e in ready(self.p).items() if e["kind"] == "delete"}
        self.assertEqual(list(deletes), ["102"])
        self.assertEqual(deletes["102"]["tool"], "delete_ranking_rule")
        self.assertEqual(deletes["102"]["undo"], [])
        self.assertIn("can't be undone", deletes["102"]["undo_note"])
        # An enabled rule asked to be deleted is planned as a disable instead.
        conv = ready(self.p)["103"]
        self.assertEqual(conv["kind"], "disable")
        self.assertIn("plans a disable instead", conv["warnings"][0])
        # Disabled recently and not expired: blocked for now.
        self.assertIn("delete_min_disabled_days", blocked(self.p)["104"]["problems"][0])

    def test_blocked(self):
        b = blocked(self.p)
        self.assertIn("running A/B test", b["105"]["problems"][0])  # isLive on the rule
        self.assertIn("running A/B test", b["111"]["problems"][0])  # in a "Running" experiment's bucket
        self.assertIn("owner_confirmed", b["106"]["problems"][0])  # protected name
        self.assertIn("no write tool", b["110"]["problems"][0])  # media rule
        self.assertIn("not editable", b["113"]["problems"][0])
        enable = [e for e in self.p["changes"] if e.get("requested") == "enable"]
        self.assertEqual([(e["status"], e["kind"]) for e in enable], [("blocked", "enable")])
        self.assertIn("No --rule detail", b["999"]["problems"][0])
        for e in b.values():
            self.assertEqual(e["live_impact"], "none")
        no_change = [e for e in self.p["changes"] if e["status"] == "no_change"]
        self.assertEqual([e["rule_id"] for e in no_change], ["112"])

    def test_running_status_is_case_insensitive_and_missing_counts_as_running(self):
        self.assertIn("109", ready(self.p))  # a COMPLETED experiment doesn't block
        with tempfile.TemporaryDirectory() as tmp:
            exp = Path(tmp) / "exp.json"
            exp.write_text(json.dumps({"data": [{"id": "e9", "buckets": [{"ruleIdentifierInfo": {"id": "101"}}]}]}),
                           encoding="utf-8")
            p = plan("--experiments", exp)
        disable_101 = next(e for e in p["changes"] if e["rule_id"] == "101" and e["requested"] == "disable")
        self.assertEqual(disable_101["status"], "blocked")
        self.assertIn("running A/B test", disable_101["problems"][0])

    def test_end_dates(self):
        r = ready(self.p)
        facet = r["107"]
        self.assertEqual((facet["kind"], facet["tool"]), ("update", "update_facet_rule"))
        self.assertEqual(facet["payload"]["ended_at"], 1798761599000)  # 2026-12-31 23:59:59 UTC
        self.assertEqual(facet["undo"], [])  # no previous end date: the tool can't clear one
        self.assertIn("can't clear", facet["undo_note"])
        self.assertEqual(r["108"]["undo"][0]["payload"]["ended_at"], 1793750400000 + 5 * 86_400_000)

    def test_set_queries(self):
        e = ready(self.p)["109"]
        self.assertEqual(e["payload"]["queries"], [{"query": "backpacks", "queryType": "sitesearch",
                                                    "matchType": "EXACT_MATCH"}])
        self.assertEqual(e["undo"][0]["payload"]["queries"], [{"query": "backpack", "queryType": "sitesearch",
                                                               "matchType": "EXACT_MATCH"}])

    def test_batches_and_order(self):
        r = ready(self.p)
        self.assertEqual(self.p["changes"][0]["rule_id"], "101")  # high priority first
        batched = [n for b in self.p["batches"] for n in b]
        self.assertEqual(sorted(batched), sorted(e["n"] for e in r.values()))  # only ready changes
        # Each delete is a batch of its own.
        for e in r.values():
            if e["kind"] == "delete":
                self.assertIn([e["n"]], self.p["batches"])
        for b in self.p["batches"]:
            kinds = {next(e["kind"] for e in self.p["changes"] if e["n"] == n) for n in b}
            self.assertTrue("delete" not in kinds or len(b) == 1, b)

    def test_editor_names_never_copied(self):
        self.assertNotIn("editor@example.test", json.dumps(self.p))

    def test_without_experiments_file_warns(self):
        p = plan()
        self.assertFalse(p["experiments_checked"])
        self.assertIn("search_discovery_experiments", p["warning"])
        self.assertIn("111", ready(p))  # only the isLive flag was checked

    def test_environment_and_account_are_required(self):
        self.assertEqual(plan(environment="production")["changes"][0]["payload"]["environment"], "production")
        r = run("plan", "--request", FX / "request.json", "--account", "demo_account")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--environment", r.stderr)
        r = run("plan", "--request", FX / "request.json", "--environment", "staging")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--account", r.stderr)

    def test_site_group_id_in_every_payload(self):
        p = plan("--site-group-id", "7")
        self.assertEqual(p["site_group_id"], "7")
        for e in ready(p).values():
            self.assertEqual(e["payload"]["site_group_id"], "7")
            for u in e["undo"]:
                self.assertEqual(u["payload"]["site_group_id"], "7")

    def test_batch_cap_counts_only_ready_changes(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        cap = rules["max_changes_per_batch"]
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "req.json"
            reqs = [{"rule_id": 105, "action": "disable", "priority": "high"}] * 3  # blocked: running test
            reqs += [{"rule_id": 101, "action": "disable"}] * (cap + 3)
            req.write_text(json.dumps(reqs), encoding="utf-8")
            p = plan(request=req, ids=[101, 105])
        self.assertEqual([len(b) for b in p["batches"]], [cap, 3])
        self.assertEqual(p["summary"]["blocked"], 3)

    def test_past_end_date_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "req.json"
            req.write_text(json.dumps([{"rule_id": 108, "action": "set_end_date", "end_date": "2026-01-01"}]),
                           encoding="utf-8")
            p = plan(request=req, ids=[108])
        self.assertIn("isn't in the future", p["changes"][0]["problems"][0])


class VerifyTest(unittest.TestCase):
    def verify(self, *rules, plan_file=None):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            if plan_file is None:
                plan("--out", out)
            else:
                out.write_text(plan_file, encoding="utf-8")
            args = [a for rid, path in rules for a in ("--rule", f"{rid}={path}")]
            return run("verify", "--plan", out, *args)

    def test_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            gone = Path(tmp) / "gone.json"
            gone.write_text(json.dumps({"result": {"success": False, "error": "Customization not found"}}),
                            encoding="utf-8")
            r = self.verify(("101", FX / "after_101.json"), ("107", FX / "after_107.json"), ("102", gone))
        res = {x["rule_id"]: x for x in json.loads(r.stdout)["results"]}
        self.assertEqual((res["101"]["result"], res["101"]["ok"]), ("in_place", True))
        self.assertEqual(res["107"]["result"], "not_in_place")  # end date not applied
        self.assertIn("endedAt", res["107"]["detail"])
        self.assertEqual((res["102"]["result"], res["102"]["ok"]), ("gone", True))  # not found counts as gone
        self.assertEqual(res["109"]["result"], "not_in_place")  # not read back

    def test_delete_needs_a_read_back(self):
        r = self.verify(("101", FX / "after_101.json"))
        res = {x["rule_id"]: x for x in json.loads(r.stdout)["results"]}
        self.assertEqual((res["102"]["result"], res["102"]["ok"]), ("not_in_place", False))
        self.assertIn("not read back", res["102"]["detail"])
        # A delete whose rule is still there isn't gone.
        r = self.verify(("102", FX / "rule_102.json"))
        res = {x["rule_id"]: x for x in json.loads(r.stdout)["results"]}
        self.assertEqual(res["102"]["result"], "not_in_place")

    def test_other_read_back_errors_stop(self):
        r = self.verify(("102", FX / "denied.json"))
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertIn("isn't repeated", out["error"])
        self.assertNotIn("acct_b", out["error"])

    def test_malformed_plan(self):
        for text in ("[]", json.dumps({"ok": True}), json.dumps({"ok": True, "changes": [{"n": 1}]}),
                     json.dumps({"ok": True, "changes": ["x"]})):
            r = self.verify(plan_file=text)
            self.assertEqual(r.returncode, 1, text)
            self.assertFalse(json.loads(r.stdout)["ok"])
            self.assertNotIn("Traceback", r.stderr)


class ErrorTest(unittest.TestCase):
    def test_account_errors_are_never_repeated(self):
        r = run("plan", "--request", FX / "request.json", "--rule", f"101={FX / 'denied.json'}",
                "--environment", "staging", "--account", "x")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertIn("isn't repeated", out["error"])
        self.assertNotIn("acct_b", out["error"])
        # Even a short error that names one account isn't echoed.
        with tempfile.TemporaryDirectory() as tmp:
            short = Path(tmp) / "short.json"
            short.write_text(json.dumps({"success": False, "error": "unknown account acme_secret"}), encoding="utf-8")
            r = run("plan", "--request", short, "--environment", "staging", "--account", "x")
        self.assertNotIn("acme_secret", r.stdout)

    def test_unwritable_out(self):
        r = run("plan", "--request", FX / "request.json", "--environment", "staging", "--account", "x",
                "--out", "/nonexistent-folder/plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't write it", json.loads(r.stdout)["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_bad_input(self):
        base = ("--environment", "staging", "--account", "x")
        r = run("plan", "--request", FX / "request.json", "--rule", "101", *base)
        self.assertEqual(r.returncode, 2)
        self.assertIn("<rule id>=<file>", r.stderr)
        r = run("plan", "--request", FX / "request.json", "--rule", f"999={FX / 'rule_101.json'}", *base)
        self.assertIn("holds rule 101", json.loads(r.stdout)["error"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps([{"rule_id": "abc", "action": "disable"}]), encoding="utf-8")
            r = run("plan", "--request", bad, *base)
            self.assertIn("whole number", json.loads(r.stdout)["error"])
            bad.write_text("not json", encoding="utf-8")
            r = run("plan", "--request", bad, *base)
            self.assertIn("can't read it as JSON", json.loads(r.stdout)["error"])
        r = run("plan", "--request", FX / "request.json", "--today", "tomorrow", *base)
        self.assertEqual(r.returncode, 2)

    def test_rules_have_notes(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
