"""Tests for discovery-experiment-close's close_plan.py, which builds the plan for ending an A/B test. It never
writes anything; these tests check the plan it prints. The fixtures are synthetic."""
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


def run(*args):
    """Run the script by its full path from an empty working folder; return (exit code, parsed stdout, stderr)."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True,
                           text=True, encoding="utf-8")
        leftovers = list(Path(tmp).iterdir())
    assert not leftovers or all(p.name.endswith(".json") for p in leftovers), leftovers
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def plan(experiment, *args):
    code, out, err = run("--experiment", FX / experiment, "--account", "acme", "--today", TODAY, *args)
    assert code == 0, err + json.dumps(out)
    return out


def steps(out):
    return [s["step"] for s in out["steps"]]


def writes(out):
    return [s for s in out["steps"] if s.get("write")]


class ClosePlanTest(unittest.TestCase):
    def test_ship_winner_pattern_1(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json",
                   "--rule", FX / "rule_7001.json")
        self.assertEqual(out["decision"]["keep_bucket"], "Brand boost")
        self.assertTrue(out["decision"]["ships_change"])
        self.assertFalse(out["refused"])
        self.assertEqual(steps(out), ["change_qa", "end", "read_back", "enable_winner", "archive"])
        end = out["steps"][1]
        self.assertEqual(end["tool"], "end_discovery_experiment")
        self.assertEqual(end["payload"], {"account_name": "acme", "experiment_id": 900001, "environment": "staging",
                                          "winner_bucket_id": 5002})
        self.assertIn("can't be undone", end["irreversible"])
        self.assertTrue(out["steps"][3]["conditional"])
        self.assertEqual(out["steps"][3]["undo"]["payload"]["enabled"], False)
        self.assertIn("unarchive", out["steps"][-1]["irreversible"])

    def test_every_write_is_its_own_step(self):
        out = plan("experiment_p2_running.json", "--report", FX / "report_p2_conclusive.json",
                   "--rule", FX / "rule_7010.json", "--rule", FX / "rule_7011.json")
        tools = [(s["step"], s["tool"]) for s in writes(out)]
        self.assertEqual(tools, [("end", "end_discovery_experiment"), ("disable_leftover", "update_ranking_rule"),
                                 ("enable_winner", "update_ranking_rule"), ("archive", "archive_discovery_experiment")])
        for s in writes(out):
            self.assertIn("payload", s)
            self.assertIn("live_impact", s)
        leftover = next(s for s in out["steps"] if s["step"] == "disable_leftover")
        self.assertEqual((leftover["rule_id"], leftover["payload"]["enabled"]), (7010, False))
        self.assertEqual(leftover["before"]["enabled"], True)

    def test_control_wins_keeps_default(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_inconclusive.json")
        self.assertEqual(out["decision"]["keep_bucket"], "Control")
        self.assertFalse(out["decision"]["ships_change"])
        self.assertFalse(out["refused"])
        end = next(s for s in out["steps"] if s["step"] == "end")
        self.assertNotIn("winner_bucket_id", end["payload"])  # default behaviour: end with no winner
        self.assertNotIn("change_qa", steps(out))
        leftover = next(s for s in out["steps"] if s["step"] == "disable_leftover")
        self.assertEqual(leftover["payload"]["enabled"], False)

    def test_control_with_a_rule_is_kept_as_winner(self):
        out = plan("experiment_p2_running.json", "--keep", "Current rule")
        end = next(s for s in out["steps"] if s["step"] == "end")
        self.assertEqual(end["payload"]["winner_bucket_id"], 5011)
        self.assertFalse(out["decision"]["ships_change"])

    def test_inverse_default_test_bucket_wins(self):
        out = plan("experiment_inverse_running.json", "--report", FX / "report_inverse_conclusive.json")
        self.assertEqual(out["decision"]["keep_bucket"], "Default")
        self.assertTrue(out["decision"]["ships_change"])
        self.assertIn("removing rule 7020", out["steps"][0]["what"])
        end = next(s for s in out["steps"] if s["step"] == "end")
        self.assertNotIn("winner_bucket_id", end["payload"])

    def test_inconclusive_ship_is_refused(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_inconclusive.json", "--keep", "Brand boost")
        self.assertTrue(out["refused"])
        self.assertEqual(out["steps"], [])
        self.assertTrue(any("inconclusive" in r for r in out["refusal_reasons"]))

    def test_too_short_is_refused(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json", "--today", "2026-09-28")
        # 7 days: the conclusive bucket isn't recommended, and forcing it is refused.
        self.assertEqual(out["decision"]["keep_bucket"], "Control")
        forced = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json", "--today", "2026-09-28",
                      "--keep", "Brand boost")
        self.assertTrue(forced["refused"])
        self.assertTrue(any("min_days" in r for r in forced["refusal_reasons"]))

    def test_override(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_inconclusive.json", "--keep", "5002",
                   "--override")
        self.assertFalse(out["refused"])
        self.assertTrue(out["override_used"])
        self.assertTrue(any(w.startswith("Overridden:") for w in out["warnings"]))
        self.assertIn("end", steps(out))

    def test_guardrail_and_missing_report_and_zero_data(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_guardrail.json", "--keep", "Brand boost")
        self.assertTrue(any(r.startswith("Guardrail aov") for r in out["refusal_reasons"]))
        out = plan("experiment_p1_running.json", "--keep", "Brand boost")
        self.assertTrue(any("No experiment report" in r for r in out["refusal_reasons"]))
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_zero.json", "--keep", "Brand boost")
        self.assertTrue(any("0 visits" in r for r in out["refusal_reasons"]))

    def test_split_imbalance_warns(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_imbalanced.json")
        self.assertFalse(out["refused"])
        self.assertTrue(any("allocation may be broken" in w for w in out["warnings"]))

    def test_keeping_control_against_a_winner_warns(self):
        out = plan("experiment_p1_running.json", "--report", FX / "report_p1_conclusive.json", "--keep", "Control")
        self.assertTrue(any("Keeping the control" in w for w in out["warnings"]))

    def test_completed_draft_no_metric(self):
        out = plan("experiment_completed.json")
        end = next(s for s in out["steps"] if s["step"] == "end")
        self.assertFalse(end["write"])
        self.assertIn("archive", steps(out))
        out = plan("experiment_draft.json")
        self.assertTrue(out["refused"])
        self.assertIn("DRAFT", out["refusal_reasons"][0])
        out = plan("experiment_no_metric.json")
        self.assertTrue(any("default_metric" in w for w in out["warnings"]))
        self.assertEqual(out["experiment"]["metric"], "rpv")

    def test_no_personal_data_in_output(self):
        out = plan("experiment_p2_running.json", "--report", FX / "report_p2_conclusive.json",
                   "--rule", FX / "rule_7010.json")
        self.assertNotIn("editor@example.test", json.dumps(out))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plan.json"
            code, out, _ = run("--experiment", FX / "experiment_p1_running.json", "--today", TODAY, "--out", target)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), out)

    def test_bad_input(self):
        cases = [(("--experiment", FX / "denied.json"), "ACCESS_DENIED"),
                 (("--experiment", FX / "account_error.json"), "isn't repeated"),
                 (("--experiment", FX / "missing.json"), "can't read"),
                 (("--experiment", FX / "experiment_bad_start.json"), "startedAt"),
                 (("--experiment", FX / "experiment_p1_running.json", "--report", FX / "report_wrong_buckets.json"),
                  "no row for bucket"),
                 (("--experiment", FX / "experiment_p1_running.json", "--keep", "Nope"), "matches no bucket"),
                 (("--experiment", FX / "experiment_p1_running.json", "--rule", FX / "report_p1_zero.json"),
                  "not a get_ranking_rule result")]
        for args, needle in cases:
            code, out, err = run(*args)
            self.assertEqual(code, 1, args)
            self.assertIn(needle, out["error"])
            self.assertNotIn("alpha_shop", out["error"])
            self.assertEqual(err, "")
        code, _, err = run("--experiment", FX / "experiment_p1_running.json", "--today", "nope")
        self.assertEqual(code, 2)
        self.assertIn("not a date", err)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
