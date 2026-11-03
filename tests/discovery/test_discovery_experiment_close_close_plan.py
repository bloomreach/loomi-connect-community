"""Tests for discovery-experiment-close's close_plan.py, which builds and checks the plan for ending an A/B test. It
never writes anything; these tests check the plan and the verify results it prints. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-experiment-close"
SCRIPT = SKILL / "scripts/close_plan.py"
FX = ROOT / "tests/fixtures/discovery/experiment_close"
TODAY = "2026-10-21"  # 30 days after the fixtures' start date
CHANGE_KEYS = {"n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings"}


def run(*args):
    """Run the script by its full path from an empty working folder; return (exit code, parsed stdout, stderr)."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True,
                           text=True, encoding="utf-8")
        leftovers = list(Path(tmp).iterdir())
    assert not leftovers or all(p.name.endswith(".json") for p in leftovers), leftovers
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def plan(experiment, *args):
    code, out, err = run("plan", "--experiment", FX / experiment, "--account", "acme", "--today", TODAY, *args)
    assert code == 0, err + json.dumps(out)
    return out


def kinds(out):
    return [c["kind"] for c in out["changes"]]


def by_kind(out, kind):
    return [c for c in out["changes"] if c["kind"] == kind]


class PlanShapeTest(unittest.TestCase):
    def test_ship_winner_pattern_1(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json",
                   "--rule", f"7001={FX / 'rule_7001.json'}")
        self.assertEqual((out["account"], out["environment"], out["site_group_id"]), ("acme", "staging", None))
        self.assertEqual(out["decision"]["keep_bucket"], "Brand boost")
        self.assertTrue(out["decision"]["ships_change"])
        self.assertFalse(out["refused"])
        self.assertEqual(kinds(out), ["end", "enable", "archive"])
        self.assertTrue(any("discovery-change-qa" in c for c in out["checks_before"]))
        for c in out["changes"]:
            self.assertLessEqual(CHANGE_KEYS, set(c))
            self.assertEqual(c["status"], "ready")
        end = out["changes"][0]
        self.assertEqual(end["tool"], "end_discovery_experiment")
        self.assertEqual(end["payload"], {"account_name": "acme", "environment": "staging", "experiment_id": 900001,
                                          "winner_bucket_id": 5002})
        self.assertEqual((end["undo"], end["live_impact"]), ([], "live"))
        self.assertTrue(any("can't be undone" in w for w in end["warnings"]))
        enable = out["changes"][1]
        self.assertTrue(enable["conditional"])
        self.assertEqual(enable["undo"][0]["payload"]["enabled"], False)
        self.assertEqual(enable["before"]["enabled"], True)
        archive = out["changes"][-1]
        self.assertEqual((archive["undo"], archive["live_impact"]), ([], "none"))
        self.assertTrue(any("unarchive" in w for w in archive["warnings"]))
        # Every step is a batch of its own.
        self.assertEqual(out["batches"], [[1], [2], [3]])

    def test_pattern_2_steps(self):
        out = plan("experiment_p2_running.json", "--report", FX / "report_p2_conclusive.json",
                   "--rule", f"7010={FX / 'rule_7010.json'}", "--rule", f"7011={FX / 'rule_7011.json'}")
        self.assertEqual([(c["kind"], c["tool"]) for c in out["changes"]],
                         [("end", "end_discovery_experiment"), ("disable", "update_ranking_rule"),
                          ("enable", "update_ranking_rule"), ("archive", "archive_discovery_experiment")])
        leftover = by_kind(out, "disable")[0]
        self.assertEqual((leftover["payload"]["rule_id"], leftover["payload"]["enabled"]), (7010, False))
        self.assertEqual(leftover["before"]["enabled"], True)

    def test_site_group_id_in_every_payload(self):
        out = plan("experiment_p2_running.json", "--report", FX / "report_p2_conclusive.json", "--site-group-id", "42")
        self.assertEqual(out["site_group_id"], 42)
        for c in out["changes"]:
            self.assertEqual(c["payload"]["site_group_id"], 42, c["kind"])
            for u in c["undo"]:
                self.assertEqual(u["payload"]["site_group_id"], 42)
        out = plan("experiment_p1_running.json", "--site-group-id", "uk-site")
        self.assertEqual(out["changes"][0]["payload"]["site_group_id"], "uk-site")

    def test_control_wins_keeps_default(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_inconclusive.json")
        self.assertEqual(out["decision"]["keep_bucket"], "Control")
        self.assertFalse(out["decision"]["ships_change"])
        self.assertFalse(out["refused"])
        self.assertNotIn("winner_bucket_id", out["changes"][0]["payload"])  # default behaviour: end with no winner
        self.assertEqual(out["checks_before"], [])
        self.assertEqual(by_kind(out, "disable")[0]["payload"]["enabled"], False)

    def test_control_with_a_rule_is_kept_as_winner(self):
        out = plan("experiment_p2_running.json", "--keep", "Current rule")
        self.assertEqual(out["changes"][0]["payload"]["winner_bucket_id"], 5011)
        self.assertFalse(out["decision"]["ships_change"])

    def test_inverse_default_test_bucket_wins(self):
        out = plan("experiment_inverse_running.json", "--report", FX / "report_inverse_conclusive.json")
        self.assertEqual(out["decision"]["keep_bucket"], "Default")
        self.assertTrue(out["decision"]["ships_change"])
        self.assertIn("removing rule 7020", out["checks_before"][0])
        self.assertNotIn("winner_bucket_id", out["changes"][0]["payload"])


class RefusalTest(unittest.TestCase):
    def assert_blocked(self, out, needle):
        self.assertTrue(out["refused"])
        self.assertTrue(out["changes"])
        for c in out["changes"]:
            self.assertEqual(c["status"], "blocked")
            self.assertTrue(any(needle in p for p in c["problems"]), c["problems"])
        self.assertEqual(out["batches"], [])

    def test_inconclusive_ship_is_blocked(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_inconclusive.json", "--keep", "Brand boost")
        self.assert_blocked(out, "inconclusive")

    def test_too_short_is_blocked(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json", "--today", "2026-09-28")
        self.assertEqual(out["decision"]["keep_bucket"], "Control")  # the conclusive bucket isn't recommended at 7 days
        forced = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json", "--today",
                      "2026-09-28", "--keep", "Brand boost")
        self.assert_blocked(forced, "min_days")

    def test_override(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_inconclusive.json", "--keep", "5002",
                   "--override")
        self.assertFalse(out["refused"])
        self.assertTrue(out["override_used"])
        self.assertTrue(any(w.startswith("Overridden:") for w in out["warnings"]))
        self.assertEqual({c["status"] for c in out["changes"]}, {"ready"})

    def test_guardrail_and_missing_report_and_zero_data(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_guardrail.json", "--keep", "Brand boost")
        self.assertTrue(any(r.startswith("Guardrail aov") for r in out["refusal_reasons"]))
        out = plan("experiment_p1_running.json", "--keep", "Brand boost")
        self.assert_blocked(out, "No experiment report")
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_zero.json", "--keep", "Brand boost")
        self.assert_blocked(out, "0 visits")

    def test_split_imbalance_warns(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_imbalanced.json")
        self.assertFalse(out["refused"])
        self.assertTrue(any("allocation may be broken" in w for w in out["warnings"]))

    def test_keeping_control_against_a_winner_warns(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json", "--keep", "Control")
        self.assertTrue(any("Keeping the control" in w for w in out["warnings"]))

    def test_completed_draft_no_metric(self):
        out = plan("experiment_completed.json")
        end = out["changes"][0]
        self.assertEqual((end["kind"], end["status"], end["tool"]), ("end", "no_change", None))
        self.assertIn("archive", kinds(out))
        self.assertNotIn(1, [n for b in out["batches"] for n in b])
        out = plan("experiment_draft.json")
        self.assertTrue(out["refused"])
        self.assertIn("DRAFT", out["refusal_reasons"][0])
        self.assertEqual((out["changes"], out["batches"]), ([], []))
        out = plan("experiment_no_metric.json")
        self.assertTrue(any("default_metric" in w for w in out["warnings"]))
        self.assertEqual(out["experiment"]["metric"], "rpv")


class RequiredContextTest(unittest.TestCase):
    def test_account_is_required(self):
        code, _, err = run("plan", "--experiment", FX / "experiment_p1_running.json", "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("--account", err)

    def test_environment_never_assumed(self):
        code, out, _ = run("plan", "--experiment", FX / "experiment_no_env.json", "--account", "acme", "--today", TODAY)
        self.assertEqual(code, 1)
        self.assertIn("never assumed", out["error"])
        out = plan("experiment_no_env.json", "--environment", "Production")
        self.assertEqual(out["environment"], "production")
        self.assertEqual(out["changes"][0]["payload"]["environment"], "production")

    def test_environment_must_match_the_experiment(self):
        code, out, _ = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                           "--environment", "production", "--today", TODAY)
        self.assertEqual(code, 1)
        self.assertIn("fetched from staging", out["error"])
        code, _, err = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                           "--environment", "dev")
        self.assertEqual(code, 2)
        self.assertIn("production or staging", err)

    def test_rule_takes_id_equals_file(self):
        code, _, err = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                           "--rule", FX / "rule_7001.json")
        self.assertEqual(code, 2)
        self.assertIn("<rule id>=<file>", err)
        code, out, _ = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                           "--rule", f"7999={FX / 'rule_7001.json'}")
        self.assertEqual(code, 1)
        self.assertIn("not rule 7999", out["error"])


class VerifyTest(unittest.TestCase):
    def write_plan(self, tmp):
        path = Path(tmp) / "plan.json"
        code, _, err = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme", "--today",
                           TODAY, "--report", FX / "report_p1_conclusive.json", "--out", path)
        self.assertEqual(code, 0, err)
        return path

    def results(self, out):
        return {r["kind"]: r["result"] for r in out["results"]}

    def test_after_ending(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write_plan(tmp)
            _, out, _ = run("verify", "--plan", p, "--experiment", FX / "experiment_p1_ended.json",
                            "--rule", f"7001={FX / 'rule_7001.json'}")
        self.assertEqual(self.results(out), {"end": "in_place", "enable": "in_place", "archive": "not_in_place"})
        enable = next(r for r in out["results"] if r["kind"] == "enable")
        self.assertIn("already in the right state", enable["action"])
        self.assertFalse(out["all_in_place"])

    def test_rule_left_off_needs_the_conditional_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write_plan(tmp)
            _, out, _ = run("verify", "--plan", p, "--rule", f"7001={FX / 'rule_7001_disabled.json'}")
        enable = next(r for r in out["results"] if r["kind"] == "enable")
        self.assertEqual(enable["result"], "not_in_place")
        self.assertIn("its own yes", enable["action"])
        self.assertEqual(self.results(out)["end"], "not_checked")

    def test_sync_pending_and_archived_and_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write_plan(tmp)
            _, out, _ = run("verify", "--plan", p, "--experiment", FX / "experiment_p1_archived.json",
                            "--rule", f"7001={FX / 'rule_7001_pending.json'}")
            self.assertEqual(self.results(out), {"end": "in_place", "enable": "in_place", "archive": "in_place"})
            self.assertIn("syncStatus is PENDING", next(r for r in out["results"] if r["kind"] == "enable")["detail"])
            _, out, _ = run("verify", "--plan", p, "--rule", f"7001={FX / 'rule_not_found.json'}")
            self.assertEqual(self.results(out)["enable"], "gone")

    def test_account_error_stops_verify_instead_of_counting_as_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write_plan(tmp)
            bad = Path(tmp) / "account_error.json"
            bad.write_text(json.dumps({"success": False, "error": "Account 'acme' not found. Accessible: alpha, beta"}),
                           encoding="utf-8")
            code, out, _ = run("verify", "--plan", p, "--rule", f"7001={bad}")
        self.assertEqual(code, 1)
        self.assertIn("error about the account name", out["error"])
        self.assertNotIn("alpha", json.dumps(out))

    def test_bad_plan_and_denied_readback(self):
        code, out, _ = run("verify", "--plan", FX / "rule_7001.json")
        self.assertEqual(code, 1)
        self.assertIn("not a plan", out["error"])
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write_plan(tmp)
            code, out, _ = run("verify", "--plan", p, "--experiment", FX / "denied.json")
        self.assertEqual(code, 1)
        self.assertIn("couldn't run", out["error"])


class ErrorsTest(unittest.TestCase):
    def test_no_personal_data_in_output(self):
        out = plan("experiment_p2_running.json", "--report", FX / "report_p2_conclusive.json",
                   "--rule", f"7010={FX / 'rule_7010.json'}")
        self.assertNotIn("editor@example.test", json.dumps(out))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plan.json"
            code, out, _ = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                               "--today", TODAY, "--out", target)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), out)
            code, out, err = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                                 "--today", TODAY, "--out", Path(tmp) / "missing" / "plan.json")
            self.assertEqual(code, 1)
            self.assertIn("can't write", out["error"])
            self.assertEqual(err, "")

    def test_account_errors_are_never_echoed(self):
        code, out, _ = run("plan", "--experiment", FX / "account_error.json", "--account", "acme")
        self.assertEqual(code, 1)
        self.assertIn("isn't repeated", out["error"])
        self.assertNotIn("alpha_shop", out["error"])

    def test_bad_input(self):
        cases = [(("--experiment", FX / "denied.json"), "ACCESS_DENIED"),
                 (("--experiment", FX / "missing.json"), "can't read"),
                 (("--experiment", FX / "experiment_bad_start.json", "--environment", "staging"), "startedAt"),
                 (("--experiment", FX / "experiment_p1_running.json", "--report", FX / "report_wrong_buckets.json"),
                  "no row for bucket"),
                 (("--experiment", FX / "experiment_p1_running.json", "--keep", "Nope"), "matches no bucket"),
                 (("--experiment", FX / "experiment_p1_running.json", "--rule", f"7001={FX / 'report_p1_zero.json'}"),
                  "not a get_ranking_rule result")]
        for args, needle in cases:
            code, out, err = run("plan", "--account", "acme", *args)
            self.assertEqual(code, 1, args)
            self.assertIn(needle, out["error"])
            self.assertEqual(err, "")
        code, _, err = run("plan", "--experiment", FX / "experiment_p1_running.json", "--account", "acme",
                           "--today", "nope")
        self.assertEqual(code, 2)
        self.assertIn("not a date", err)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
