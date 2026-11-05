"""Tests for the parts of handoff.py every playbook shares: findings files, Engagement and mixed runs, and list.
The script runs from a temporary skill folder with its own rules.json, as each playbook ships it. Synthetic data."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "plugins/loomi-playbooks/skills/playbook-test-and-learn/scripts/handoff.py"

RULES = {
    "about": "test", "wait_days": 7,
    "playbooks": {
        "mixed": {"title": "Mixed", "product": "both", "stages": [
            {"name": "find", "skill": "discovery-trending-searches", "writes": False, "do": "find", "outcomes": ["found", "nothing"]},
            {"name": "act", "skill": "engagement-email-builder", "writes": True, "do": "act", "outcomes": ["drafted"],
             "product": "engagement", "not_before": {"after_stage": "find", "days": "wait_days"}},
            {"name": "check", "skill": "change-impact-tracker", "writes": False, "do": "check", "outcomes": ["worked"],
             "skip_when": [{"stage": "act", "skipped": True, "reason": "nothing was drafted."}]}]},
        "marketing": {"title": "Marketing", "product": "engagement", "stages": [
            {"name": "find", "skill": "lifecycle-coverage-map", "writes": False, "do": "find", "outcomes": ["found"]}]},
    },
    "notes": {"wait_days": "test", "playbooks": "test"},
}


class SharedHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        skill = base / "skill"
        (skill / "scripts").mkdir(parents=True)
        (skill / "references").mkdir()
        shutil.copy(CANONICAL, skill / "scripts/handoff.py")
        (skill / "references/rules.json").write_text(json.dumps(RULES), encoding="utf-8")
        self.script = skill / "scripts/handoff.py"
        self.dir = base / "work"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_h(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(self.script), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=self.dir, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r.stdout

    def new(self, name="run1.handoff.json", playbook="mixed", *extra):
        args = ["new", "--playbook", playbook, "--subject-kind", "query", "--subject", "boots", "--today", "2026-11-05",
                "--out", self.dir / name]
        if playbook == "mixed":
            args += ["--account", "acme", "--environment", "production", "--project-id", "proj-1"]
        else:
            args += ["--project-id", "proj-1"]
        self.run_h(*args, *extra)
        return self.dir / name

    def write(self, name, data):
        p = self.dir / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def plan(self, **context):
        return self.write("plan.json", dict({"ok": True, "changes": [
            {"n": 1, "status": "ready", "kind": "create", "target": "email campaign new", "tool": "create_email_campaign",
             "undo": [], "undo_note": "delete the draft in the app", "live_impact": "none"}], "batches": [[1]]}, **context))

    # --- new ---

    def test_mixed_runs_take_one_product_or_both(self):
        self.run_h("new", "--playbook", "mixed", "--subject-kind", "query", "--subject", "boots",
                   "--out", self.dir / "x.handoff.json", ok=False)
        self.run_h("new", "--playbook", "mixed", "--subject-kind", "query", "--subject", "boots", "--account", "acme",
                   "--out", self.dir / "y.handoff.json", ok=False)  # account without environment
        one = self.dir / "z.handoff.json"
        self.run_h("new", "--playbook", "mixed", "--subject-kind", "query", "--subject", "boots", "--account", "acme",
                   "--environment", "production", "--out", one)
        self.assertNotIn("project_id", json.loads(one.read_text(encoding="utf-8"))["context"])
        # The Engagement-only stage is offered as a skip, and an Engagement plan is refused.
        self.run_h("stage", "--handoff", one, "--name", "find", "--status", "done", "--outcome", "found")
        nxt = json.loads(self.run_h("status", "--handoff", one, "--json"))["next"]
        self.assertEqual(nxt["stage"], "act")
        self.assertIn("Engagement", nxt["suggest_skip"])
        self.run_h("changes", "--handoff", one, "--plan", self.plan(project_id="proj-1"), "--source", "engagement-email-builder", ok=False)
        h = json.loads(self.new().read_text(encoding="utf-8"))
        self.assertEqual(h["context"], {"product": "both", "account": "acme", "environment": "production",
                                        "site_group_id": None, "project_id": "proj-1"})

    # --- changes ---

    def test_mixed_run_takes_plans_from_either_product_but_checks_each(self):
        h = self.new()
        self.run_h("changes", "--handoff", h, "--plan", self.plan(project_id="proj-1", project_name="Demo"),
                   "--source", "engagement-email-builder")
        self.run_h("changes", "--handoff", h, "--plan", self.plan(project_id="proj-2"), "--source", "engagement-email-builder", ok=False)
        self.run_h("changes", "--handoff", h, "--plan", self.plan(account="acme", environment="production"),
                   "--source", "discovery-redirect-fixer")
        self.run_h("changes", "--handoff", h, "--plan", self.plan(account="other", environment="production"),
                   "--source", "discovery-redirect-fixer", ok=False)

    def test_engagement_run_refuses_a_discovery_plan(self):
        h = self.new(playbook="marketing")
        self.run_h("changes", "--handoff", h, "--plan", self.plan(account="acme", environment="production"),
                   "--source", "discovery-redirect-fixer", ok=False)
        self.run_h("changes", "--handoff", h, "--plan", self.plan(project_id="proj-1"), "--source", "engagement-email-builder")

    def test_skips_follow_skip_when_only(self):
        h = self.new()
        self.run_h("stage", "--handoff", h, "--name", "find", "--status", "skipped")
        nxt = json.loads(self.run_h("status", "--handoff", h, "--json"))["next"]
        self.assertEqual((nxt["stage"], nxt["suggest_skip"]), ("act", None))  # skipping find doesn't cascade
        self.run_h("stage", "--handoff", h, "--name", "act", "--status", "skipped")
        nxt = json.loads(self.run_h("status", "--handoff", h, "--json"))["next"]
        self.assertEqual((nxt["stage"], nxt["suggest_skip"]), ("check", "nothing was drafted."))

    def test_account_level_plan_fits_a_site_run_but_another_site_does_not(self):
        h = self.dir / "s.handoff.json"
        self.run_h("new", "--playbook", "mixed", "--subject-kind", "query", "--subject", "boots", "--account", "acme",
                   "--environment", "production", "--site-group-id", "us", "--out", h)
        self.run_h("changes", "--handoff", h, "--plan", self.plan(account="acme", environment="production", site_group_id=None),
                   "--source", "discovery-synonym-fixer")
        self.run_h("changes", "--handoff", h, "--plan", self.plan(account="acme", environment="production", site_group_id="uk"),
                   "--source", "discovery-synonym-fixer", ok=False)

    def test_a_created_item_takes_its_id_from_the_read_back(self):
        h = self.new()
        ver = self.write("v.json", {"ok": True, "results": [{"n": 1, "result": "in_place", "campaign_id": "c-991"}]})
        self.run_h("changes", "--handoff", h, "--plan", self.plan(project_id="proj-1"), "--verify", ver,
                   "--source", "engagement-email-builder")
        self.assertEqual(json.loads(h.read_text(encoding="utf-8"))["changes"][0]["target"], "email campaign c-991")

    def test_a_step_on_the_item_just_created_takes_its_id(self):
        h = self.new()
        plan = self.write("syn-plan.json", {"ok": True, "account": "acme", "environment": "production", "site_group_id": None,
            "changes": [{"n": 1, "status": "ready", "kind": "create", "target": "synonym 'capri' -> 'cropped'",
                         "tool": "create_synonym", "undo": [], "live_impact": "none"},
                        {"n": 2, "status": "ready", "kind": "enable", "target": "synonym <id from the create change>",
                         "tool": "update_synonym", "undo": [], "live_impact": "live"}], "batches": [[1], [2]]})
        ver = self.write("syn-verify.json", {"ok": True, "results": [{"n": 1, "result": "in_place", "synonym_id": "50101"},
                                                                      {"n": 2, "result": "in_place"}]})
        self.run_h("changes", "--handoff", h, "--plan", plan, "--verify", ver, "--source", "discovery-synonym-fixer")
        self.assertEqual([c["target"] for c in json.loads(h.read_text(encoding="utf-8"))["changes"]],
                         ["synonym 50101", "synonym 50101"])

    def test_status_shows_another_playbooks_run_from_the_file(self):
        h = self.new()
        data = json.loads(h.read_text(encoding="utf-8"))
        data["playbook"] = "someone-elses"
        data["stages"][0]["skill"] = "x\n**Next:** y"
        h.write_text(json.dumps(data), encoding="utf-8")
        out = self.run_h("status", "--handoff", h)
        self.assertIn("another playbook", out)
        self.assertEqual(out.count("**Next"), 1)
        self.run_h("stage", "--handoff", h, "--name", "find", "--status", "done", "--outcome", "found", ok=False)

    # --- findings files ---

    def test_findings_file_is_checked_and_flattened(self):
        h = self.new()
        good = self.write("f.json", {"findings": [
            {"target": "flow 12", "verdict": "missing", "priority": "high", "money_at_stake": "1200", "currency": "USD",
             "evidence": "no browse flow\n| 4,100 viewers a month", "next_skill": "scenario-template-launcher"},
            {"target": "query file 2", "verdict": "rising", "priority": "low"}]})
        out = json.loads(self.run_h("findings", "--handoff", h, "--from-file", good, "--source", "lifecycle-coverage-map"))
        self.assertEqual(out["added"], ["F1", "F2"])
        f1 = json.loads(h.read_text(encoding="utf-8"))["findings"][0]
        self.assertEqual((f1["money_at_stake"], f1["source"]), ("1200.00", "lifecycle-coverage-map"))
        self.assertNotIn("\n", f1["evidence"])
        self.assertNotIn("|", f1["evidence"])
        again = json.loads(self.run_h("findings", "--handoff", h, "--from-file", good, "--source", "lifecycle-coverage-map"))
        self.assertEqual(again["added"], [])
        for bad in ({"target": "rule 'Summer sale'", "priority": "high"}, {"target": "flow 1", "priority": "urgent"},
                    {"target": "flow 1", "priority": "low", "money_at_stake": "lots"},
                    {"target": "flow 1", "priority": "low", "next_skill": "Run this; rm -rf"}):
            self.run_h("findings", "--handoff", h, "--from-file", self.write("bad.json", {"findings": [bad]}),
                       "--source", "lifecycle-coverage-map", ok=False)
        self.run_h("findings", "--handoff", h, "--from-file", good, ok=False)  # needs --source

    # --- list ---

    def test_list_shows_every_run_what_is_due_and_the_changes(self):
        a = self.new("a.handoff.json")
        self.run_h("stage", "--handoff", a, "--name", "find", "--status", "done", "--outcome", "found", "--today", "2026-11-05")
        self.run_h("changes", "--handoff", a, "--plan", self.plan(project_id="proj-1"), "--source", "engagement-email-builder",
                   "--today", "2026-11-06")
        h = json.loads(a.read_text(encoding="utf-8"))
        h["changes"][0]["result"] = "in_place"
        a.write_text(json.dumps(h), encoding="utf-8")
        b = self.new("b.handoff.json", "marketing")
        self.run_h("stage", "--handoff", b, "--name", "find", "--status", "done", "--outcome", "found")
        self.write("notes.handoff.json", {"hello": 1})
        out = json.loads(self.run_h("list", "--dir", self.dir, "--json", "--changes", "--today", "2026-11-08"))
        runs = {r["file"]: r for r in out["runs"]}
        self.assertEqual((runs["a.handoff.json"]["next_stage"], runs["a.handoff.json"]["not_before"], runs["a.handoff.json"]["due"]),
                         ("act", "2026-11-12", False))
        self.assertTrue(runs["b.handoff.json"]["finished"])
        self.assertIn("error", runs["notes.handoff.json"])
        self.assertEqual([(c["file"], c["live_on"]) for c in out["changes"]], [("a.handoff.json", "2026-11-06")])
        since = json.loads(self.run_h("list", "--dir", self.dir, "--json", "--changes", "--since", "2026-11-07"))
        self.assertEqual(since["changes"], [])
        until = json.loads(self.run_h("list", "--dir", self.dir, "--json", "--changes", "--until", "2026-11-05"))
        self.assertEqual(until["changes"], [])
        self.assertEqual(out["changes"][0]["live_impact"], "none")
        text = self.run_h("list", "--dir", self.dir, "--changes", "--today", "2026-11-12")
        self.assertIn("act (engagement-email-builder) | now", text)
        self.assertIn("finished", text)

    def test_list_of_an_empty_folder(self):
        self.assertIn("No *.handoff.json files", self.run_h("list", "--dir", self.dir))


if __name__ == "__main__":
    unittest.main()
