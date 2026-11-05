"""Tests for playbook-test-and-learn's handoff.py. They feed it the real outputs of the stage skills'
scripts (rule_impact.py and close_plan.py) run on their own synthetic fixtures, so a change to either
script's output shape that breaks the hand-off shows up here."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-playbooks/skills/playbook-test-and-learn"
SCRIPT = SKILL / "scripts/handoff.py"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
RULE_IMPACT = ROOT / "plugins/loomi-discovery/skills/discovery-query-rule-impact/scripts/rule_impact.py"
CLOSE_PLAN = ROOT / "plugins/loomi-discovery/skills/discovery-experiment-close/scripts/close_plan.py"
RI_FX = ROOT / "tests/fixtures/discovery/query_rule_impact"
CL_FX = ROOT / "tests/fixtures/discovery/experiment_close"


def py(script, *args, cwd):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd, timeout=60)


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.h = self.dir / "run1.handoff.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_h(self, *args, ok=True):
        r = py(SCRIPT, *args, cwd=self.dir)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertFalse(json.loads(r.stdout)["ok"])
        return r.stdout

    def new(self, account="acme", environment="staging"):
        self.run_h("new", "--playbook", "test-and-learn", "--subject-kind", "query", "--subject", "gown",
                   "--account", account, "--environment", environment, "--today", "2026-11-05", "--out", self.h)

    def handoff(self):
        return json.loads(self.h.read_text(encoding="utf-8"))

    def rule_impact(self):
        out = self.dir / "rule-impact.json"
        r = py(RULE_IMPACT, "--baseline", RI_FX / "baseline.json",
               "--toggled", f"900001={RI_FX / 'off_900001.json'}", "--toggled", f"900002={RI_FX / 'off_900002.json'}",
               "--toggled", f"all={RI_FX / 'off_all.json'}", "--query-perf", RI_FX / "query_perf.json",
               "--query", "gown", "--page-size", "5", "--product-rpv", RI_FX / "rpv_table.json", "--out", out, cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out, json.loads(r.stdout)

    def close_files(self, verify=True):
        plan, ver = self.dir / "close-plan.json", self.dir / "close-verify.json"
        r = py(CLOSE_PLAN, "plan", "--experiment", CL_FX / "experiment_p1_running.json", "--account", "acme",
               "--today", "2026-11-20", "--report", CL_FX / "report_p1_conclusive.json",
               "--rule", f"7001={CL_FX / 'rule_7001.json'}", "--out", plan, cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if verify:
            r = py(CLOSE_PLAN, "verify", "--plan", plan, "--experiment", CL_FX / "experiment_p1_archived.json",
                   "--rule", f"7001={CL_FX / 'rule_7001.json'}", "--out", ver, cwd=self.dir)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return plan, ver

    def status(self, today):
        return json.loads(self.run_h("status", "--handoff", self.h, "--json", "--today", today))

    # --- the whole run ---

    def test_full_run_through_every_stage(self):
        self.new()
        self.assertEqual([s["name"] for s in self.handoff()["stages"]],
                         [s["name"] for s in RULES["playbooks"]["test-and-learn"]["stages"]])
        ri, ri_out = self.rule_impact()
        self.run_h("findings", "--handoff", self.h, "--from-rule-impact", ri, "--today", "2026-11-05")
        h = self.handoff()
        wanted = {r["name"] for r in ri_out["results"]
                  if r["verdict"] in RULES["finding_verdicts"] and r["name"] not in ("all", "all_algo")}
        self.assertTrue(wanted)
        self.assertEqual({f["rule_id"] for f in h["findings"]}, wanted)
        f1 = h["findings"][0]
        self.assertEqual(f1["next_skill"], "discovery-experiment-setup")
        self.assertEqual(f1["money_at_stake"], next(r for r in ri_out["results"] if r["name"] == f1["rule_id"])["estimated_effect"])
        self.run_h("choose", "--handoff", self.h, "--finding", f1["id"], "--status", "chosen")
        self.run_h("stage", "--handoff", self.h, "--name", "find", "--status", "done", "--outcome", "finding_chosen",
                   "--file", ri, "--today", "2026-11-05")

        self.assertEqual(self.status("2026-11-05")["next"]["stage"], "test")
        for kind, target, tool, live in (("create", "rule 900101", "create_ranking_rule_variant", "none"),
                                         ("create", "experiment 777", "create_discovery_experiment", "none"),
                                         ("start", "experiment 777", "start_discovery_experiment", "live")):
            self.run_h("change", "--handoff", self.h, "--source", "discovery-experiment-setup", "--kind", kind,
                       "--target", target, "--tool", tool, "--live-impact", live, "--today", "2026-11-05")
        self.run_h("stage", "--handoff", self.h, "--name", "test", "--status", "done", "--outcome", "started",
                   "--today", "2026-11-05")

        nxt = self.status("2026-11-10")["next"]
        self.assertEqual((nxt["stage"], nxt["ready"]), ("read-out", False))
        self.assertEqual(nxt["not_before"], "2026-11-%02d" % (5 + RULES["min_test_days"]))
        self.assertTrue(self.status("2026-11-%02d" % (5 + RULES["min_test_days"]))["next"]["ready"])
        self.run_h("stage", "--handoff", self.h, "--name", "read-out", "--status", "done", "--outcome", "winner",
                   "--today", "2026-11-20")

        plan, ver = self.close_files()
        self.run_h("changes", "--handoff", self.h, "--plan", plan, "--verify", ver,
                   "--source", "discovery-experiment-close", "--today", "2026-11-20")
        changes = self.handoff()["changes"]
        self.assertEqual([c["id"] for c in changes], ["C1", "C2", "C3", "C4", "C5", "C6"])
        close = [c for c in changes if c["source"] == "discovery-experiment-close"]
        self.assertEqual([c["kind"] for c in close], ["end", "enable", "archive"])
        self.assertTrue(all(c["result"] == "in_place" and c["finding"] == f1["id"] for c in close))
        self.assertEqual(close[0]["plan_file"], "close-plan.json")
        self.run_h("stage", "--handoff", self.h, "--name", "close", "--status", "done", "--outcome", "shipped_variant",
                   "--today", "2026-11-20")
        self.run_h("choose", "--handoff", self.h, "--finding", f1["id"], "--status", "done")

        nxt = self.status("2026-11-21")["next"]
        self.assertEqual((nxt["stage"], nxt["skill"], nxt["ready"]), ("confirm", "change-impact-tracker", False))
        self.run_h("stage", "--handoff", self.h, "--name", "confirm", "--status", "done", "--outcome", "worked",
                   "--today", "2026-12-05")
        self.assertIsNone(self.status("2026-12-05")["next"])
        self.assertIn("All stages are finished", self.run_h("status", "--handoff", self.h, "--today", "2026-12-05"))
        # Only the hand-off file and the files the stage scripts were asked to write.
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["close-plan.json", "close-verify.json", "rule-impact.json", "run1.handoff.json"])

    # --- findings ---

    def test_findings_are_counts_never_product_titles_and_added_once(self):
        self.new()
        ri, _ = self.rule_impact()
        self.run_h("findings", "--handoff", self.h, "--from-rule-impact", ri)
        first = self.handoff()["findings"]
        out = json.loads(self.run_h("findings", "--handoff", self.h, "--from-rule-impact", ri))
        self.assertEqual(out["added"], [])
        self.assertEqual(len(self.handoff()["findings"]), len(first))
        text = self.h.read_text(encoding="utf-8")
        self.assertNotIn("gown A", text)
        self.assertNotIn("Pinned", text)
        out = json.loads(self.run_h("findings", "--handoff", self.h, "--from-rule-impact", ri, "--all"))
        self.assertTrue(out["added"])
        self.assertIn("every rule", {f["target"] for f in self.handoff()["findings"]})

    def test_rejects_a_failed_rule_impact_result(self):
        self.new()
        bad = self.dir / "bad.json"
        bad.write_text('{"ok": false, "error": "x"}\n', encoding="utf-8")
        self.run_h("findings", "--handoff", self.h, "--from-rule-impact", bad, ok=False)

    def test_one_chosen_finding_at_a_time(self):
        self.new()
        ri, _ = self.rule_impact()
        self.run_h("findings", "--handoff", self.h, "--from-rule-impact", ri, "--all")
        ids = [f["id"] for f in self.handoff()["findings"]]
        self.run_h("choose", "--handoff", self.h, "--finding", ids[0], "--status", "chosen")
        self.run_h("choose", "--handoff", self.h, "--finding", ids[1], "--status", "chosen", ok=False)
        self.run_h("choose", "--handoff", self.h, "--finding", "F99", "--status", "done", ok=False)

    # --- changes ---

    def test_plan_for_another_account_or_environment_is_refused(self):
        plan, ver = self.close_files()
        self.new(account="other")
        self.run_h("changes", "--handoff", self.h, "--plan", plan, "--source", "discovery-experiment-close", ok=False)
        self.h.unlink()
        self.new(environment="production")
        self.run_h("changes", "--handoff", self.h, "--plan", plan, "--source", "discovery-experiment-close", ok=False)
        self.assertEqual(self.handoff()["changes"], [])

    def test_re_adding_a_plan_updates_and_never_downgrades_a_checked_result(self):
        self.new()
        plan, ver = self.close_files()
        self.run_h("changes", "--handoff", self.h, "--plan", plan, "--source", "discovery-experiment-close")
        self.assertEqual({c["result"] for c in self.handoff()["changes"]}, {"unverified"})
        out = json.loads(self.run_h("changes", "--handoff", self.h, "--plan", plan, "--verify", ver,
                                    "--source", "discovery-experiment-close"))
        self.assertEqual((out["added"], out["updated"], out["made"]), ([], ["C1", "C2", "C3"], 3))
        self.run_h("changes", "--handoff", self.h, "--plan", plan, "--source", "discovery-experiment-close")
        self.assertEqual({c["result"] for c in self.handoff()["changes"]}, {"in_place"})

    def test_undo_is_copied_from_the_plan(self):
        self.new()
        plan, ver = self.close_files()
        self.run_h("changes", "--handoff", self.h, "--plan", plan, "--verify", ver, "--source", "discovery-experiment-close")
        enable = next(c for c in self.handoff()["changes"] if c["kind"] == "enable")
        planned = next(c for c in json.loads(plan.read_text(encoding="utf-8"))["changes"] if c["kind"] == "enable")
        self.assertEqual(enable["undo"], planned["undo"])

    # --- stages and status ---

    def test_skips_are_suggested_from_outcomes(self):
        self.new()
        self.run_h("stage", "--handoff", self.h, "--name", "find", "--status", "done", "--outcome", "nothing_to_test")
        self.assertTrue(self.status("2026-11-05")["next"]["suggest_skip"])
        for name, outcome in (("test", "started"), ("read-out", "no_winner")):
            self.run_h("stage", "--handoff", self.h, "--name", name, "--status", "done", "--outcome", outcome)
        self.run_h("stage", "--handoff", self.h, "--name", "close", "--status", "done", "--outcome", "kept_control")
        nxt = self.status("2027-01-01")["next"]
        self.assertEqual(nxt["stage"], "confirm")
        self.assertIn("nothing changed", nxt["suggest_skip"])

    def test_unknown_stage_or_outcome_is_refused(self):
        self.new()
        self.run_h("stage", "--handoff", self.h, "--name", "deploy", "--status", "done", ok=False)
        self.run_h("stage", "--handoff", self.h, "--name", "find", "--status", "done", "--outcome", "great", ok=False)

    # --- new ---

    def test_new_refuses_to_overwrite_and_needs_the_context(self):
        self.new()
        self.run_h("new", "--playbook", "test-and-learn", "--subject-kind", "query", "--subject", "gown",
                   "--account", "acme", "--environment", "staging", "--out", self.h, ok=False)
        r = py(SCRIPT, "new", "--playbook", "test-and-learn", "--subject-kind", "query", "--subject", "gown",
               "--account", "acme", "--out", self.dir / "x.json", cwd=self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.dir / "x.json").exists())

    def test_subject_from_a_file_and_plain_text_only_inline(self):
        q = self.dir / "query.txt"
        q.write_text('robe "longue" & ruban\n', encoding="utf-8")
        self.run_h("new", "--playbook", "test-and-learn", "--subject-kind", "query", "--subject-file", q,
                   "--account", "acme", "--environment", "staging", "--out", self.h)
        self.assertEqual(self.handoff()["subject"]["value"], 'robe "longue" & ruban')
        r = py(SCRIPT, "new", "--playbook", "test-and-learn", "--subject-kind", "query", "--subject", "a;b",
               "--account", "acme", "--environment", "staging", "--out", self.dir / "y.json", cwd=self.dir)
        self.assertNotEqual(r.returncode, 0)

    def test_rejects_files_that_are_not_hand_off_files(self):
        other = self.dir / "other.json"
        other.write_text('{"format": "something-else"}\n', encoding="utf-8")
        self.run_h("status", "--handoff", other, ok=False)

    # --- the documented format ---

    def test_the_example_in_the_format_doc_is_a_valid_hand_off_file(self):
        doc = (ROOT / "docs/hand-off-format.md").read_text(encoding="utf-8")
        example = json.loads(re.search(r"```json\n(.*?)\n```", doc, re.S).group(1))
        self.h.write_text(json.dumps(example), encoding="utf-8")
        out = self.status("2026-11-21")
        self.assertEqual(out["next"]["stage"], "test")
        for key in ("format", "playbook", "context", "subject", "stages", "findings", "changes"):
            self.assertIn(key, example)
        self.assertEqual(set(example["changes"][0]), set(self.handoff_change_keys()))

    def handoff_change_keys(self):
        self.new_in(self.dir / "keys.json")
        plan, ver = self.close_files()
        self.run_h("changes", "--handoff", self.dir / "keys.json", "--plan", plan, "--source", "discovery-experiment-close")
        return json.loads((self.dir / "keys.json").read_text(encoding="utf-8"))["changes"][0].keys()

    def new_in(self, path):
        self.run_h("new", "--playbook", "test-and-learn", "--subject-kind", "query", "--subject", "gown",
                   "--account", "acme", "--environment", "staging", "--out", path)

    def test_every_rules_key_has_a_note(self):
        keys = set(RULES) - {"about", "notes"}
        self.assertEqual(keys - set(RULES["notes"]), set())
        stage_keys = {s["not_before"]["days"] for p in RULES["playbooks"].values() for s in p["stages"] if "not_before" in s}
        self.assertLessEqual(stage_keys, keys)


if __name__ == "__main__":
    unittest.main()
