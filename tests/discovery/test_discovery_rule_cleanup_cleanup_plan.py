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


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def plan(*extra, request=FX / "request.json", ids=IDS):
    rules = [a for i in ids for a in ("--rule", f"{i}={FX / f'rule_{i}.json'}")]
    r = run("plan", "--request", request, *rules, "--today", "2026-11-04", "--account", "demo_account", *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def by_id(entries):
    return {e["rule_id"]: e for e in entries}


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = plan("--experiments", FX / "experiments.json")

    def test_every_change_has_before_after_payload_and_undo(self):
        for e in self.p["changes"]:
            for key in ("before", "after", "tool", "payload", "qa"):
                self.assertIn(key, e, e["rule_id"])
            self.assertTrue(e["undo"] or e["undo_note"], e["rule_id"])
            self.assertEqual(e["payload"]["environment"], "staging")  # staging is the default
            self.assertEqual(e["payload"]["account_name"], "demo_account")

    def test_disable(self):
        e = by_id(self.p["changes"])["101"]
        self.assertEqual((e["tool"], e["payload"]["enabled"]), ("update_ranking_rule", False))
        self.assertEqual(e["undo"], {"tool": "update_ranking_rule", "payload": {
            "rule_id": 101, "environment": "staging", "account_name": "demo_account", "enabled": True}})
        self.assertEqual(e["after"]["enabled"], False)

    def test_delete_only_when_disabled_and_expired(self):
        deletes = by_id(self.p["deletes"])
        self.assertEqual(list(deletes), ["102"])
        self.assertEqual(deletes["102"]["tool"], "delete_ranking_rule")
        self.assertIsNone(deletes["102"]["undo"])
        self.assertIn("can't be undone", deletes["102"]["undo_note"])
        # An enabled rule asked to be deleted is planned as a disable instead.
        conv = by_id(self.p["changes"])["103"]
        self.assertEqual(conv["action"], "disable")
        self.assertIn("plans a disable instead", conv["converted"])
        # Disabled recently and not expired: refused for now.
        self.assertIn("delete_min_disabled_days", by_id(self.p["refused"])["104"]["why"])

    def test_refusals(self):
        refused = by_id(self.p["refused"])
        self.assertIn("running A/B test", refused["105"]["why"])  # isLive on the rule
        self.assertIn("running A/B test", refused["111"]["why"])  # in a RUNNING experiment's bucket
        self.assertIn("owner_confirmed", refused["106"]["why"])  # protected name
        self.assertIn("no write tool", refused["110"]["why"])  # media rule
        self.assertIn("not editable", refused["113"]["why"])
        enable = [e for e in self.p["refused"] if e.get("requested") == "enable"]
        self.assertEqual(len(enable), 1)
        self.assertEqual(self.p["missing"][0]["rule_id"], "999")
        self.assertEqual(self.p["noop"][0]["rule_id"], "112")

    def test_completed_experiment_does_not_block(self):
        self.assertIn("109", by_id(self.p["changes"]))

    def test_end_dates(self):
        changes = by_id(self.p["changes"])
        facet = changes["107"]
        self.assertEqual(facet["tool"], "update_facet_rule")
        self.assertEqual(facet["payload"]["ended_at"], 1798761599000)  # 2026-12-31 23:59:59 UTC
        self.assertIsNone(facet["undo"])  # no previous end date: the tool can't clear one
        self.assertIn("can't clear", facet["undo_note"])
        extend = changes["108"]
        self.assertEqual(extend["undo"]["payload"]["ended_at"], 1793750400000 + 5 * 86_400_000)

    def test_set_queries(self):
        e = by_id(self.p["changes"])["109"]
        self.assertEqual(e["payload"]["queries"], [{"query": "backpacks", "queryType": "sitesearch",
                                                    "matchType": "EXACT_MATCH"}])
        self.assertEqual(e["undo"]["payload"]["queries"], [{"query": "backpack", "queryType": "sitesearch",
                                                            "matchType": "EXACT_MATCH"}])

    def test_priority_order_and_numbering(self):
        self.assertEqual(self.p["changes"][0]["rule_id"], "101")  # high first
        self.assertEqual([e["n"] for e in self.p["changes"] + self.p["deletes"]],
                         list(range(1, len(self.p["changes"]) + len(self.p["deletes"]) + 1)))

    def test_editor_names_never_copied(self):
        self.assertNotIn("editor@example.test", json.dumps(self.p))

    def test_without_experiments_file_warns(self):
        p = plan()
        self.assertFalse(p["experiments_checked"])
        self.assertIn("search_discovery_experiments", p["warning"])
        self.assertIn("111", by_id(p["changes"]))  # only the isLive flag was checked

    def test_production_needs_saying_so(self):
        p = plan("--environment", "production")
        self.assertEqual(p["changes"][0]["payload"]["environment"], "production")

    def test_batch_cap(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        cap = rules["max_changes_per_batch"]
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "req.json"
            req.write_text(json.dumps([{"rule_id": 101, "action": "disable"}] * (cap + 3)), encoding="utf-8")
            p = plan(request=req, ids=[101])
        self.assertEqual(len(p["changes"]), cap)
        self.assertEqual(len(p["next_batch"]), 3)

    def test_past_end_date_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "req.json"
            req.write_text(json.dumps([{"rule_id": 108, "action": "set_end_date", "end_date": "2026-01-01"}]),
                           encoding="utf-8")
            p = plan(request=req, ids=[108])
        self.assertIn("isn't in the future", p["refused"][0]["why"])


class VerifyTest(unittest.TestCase):
    def test_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            plan("--out", out)
            r = run("verify", "--plan", out, "--rule", f"101={FX / 'after_101.json'}",
                    "--rule", f"107={FX / 'after_107.json'}")
        res = by_id(json.loads(r.stdout)["results"])
        self.assertTrue(res["101"]["ok"])
        self.assertFalse(res["107"]["ok"])  # end date not applied
        self.assertIn("endedAt", res["107"]["detail"])
        self.assertTrue(res["102"]["ok"])  # deleted: not read back
        self.assertFalse(res["109"]["ok"])  # not read back


class ErrorTest(unittest.TestCase):
    def test_account_list_error_is_not_repeated(self):
        r = run("plan", "--request", FX / "request.json", "--rule", f"101={FX / 'denied.json'}")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertIn("isn't repeated", out["error"])
        self.assertNotIn("acct_b", out["error"])

    def test_bad_input(self):
        r = run("plan", "--request", FX / "request.json", "--rule", "101")
        self.assertEqual(r.returncode, 2)
        self.assertIn("<rule id>=<file>", r.stderr)
        r = run("plan", "--request", FX / "request.json", "--rule", f"999={FX / 'rule_101.json'}")
        self.assertIn("holds rule 101", json.loads(r.stdout)["error"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps([{"rule_id": "abc", "action": "disable"}]), encoding="utf-8")
            r = run("plan", "--request", bad)
            self.assertIn("whole number", json.loads(r.stdout)["error"])
            bad.write_text("not json", encoding="utf-8")
            r = run("plan", "--request", bad)
            self.assertIn("can't read it as JSON", json.loads(r.stdout)["error"])
        r = run("plan", "--request", FX / "request.json", "--today", "tomorrow")
        self.assertEqual(r.returncode, 2)

    def test_rules_have_notes(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
