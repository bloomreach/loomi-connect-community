"""Tests for discovery-synonym-fixer's synonym_plan.py, which plans synonym writes before anything is written.
Fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-synonym-fixer"
SCRIPT = SKILL / "scripts/synonym_plan.py"
FX = ROOT / "tests/fixtures/discovery/synonym_fixer"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        written = sorted(p.name for p in Path(tmp).iterdir())
    return r, (json.loads(r.stdout) if r.stdout.strip() else None), written


def plan(request="request.json", *extra):
    r, out, _ = run("--request", FX / request, "--existing", FX / "existing.json",
                    "--experiments", FX / "experiments.json", *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return out, {c["n"]: c for c in out["changes"]}


def problem(change, text):
    return any(text in p for p in change["problems"])


class PlanTest(unittest.TestCase):
    def test_every_planned_change_has_payload_before_after_and_undo(self):
        out, ch = plan()
        for c in ch.values():
            if c["status"] != "planned":
                continue
            self.assertIn("payload", c)
            self.assertIn("undo", c)
            if c["action"] != "create":
                self.assertIsNotNone(c["before"])
            if c["action"] != "delete":
                self.assertIsNotNone(c["after"])
        self.assertEqual(out["summary"], {"requested": 24, "planned": 8, "blocked": 16, "deletes": 1, "reverts": 0})

    def test_update_payloads_are_complete(self):
        # update_synonym defaults to one-way and enabled, so every update sends all four fields.
        _, ch = plan()
        for n in (3, 4, 5):
            p = ch[n]["payload"]
            self.assertTrue(set(p) >= {"synonym_id", "source_synonym", "target_synonym", "group_synonym", "enabled"}, n)
        self.assertEqual(ch[4]["payload"], {"synonym_id": 103, "source_synonym": "sneakers,trainers,runners",
                                            "target_synonym": "", "group_synonym": True, "enabled": True,
                                            "account_name": "acme_outdoors", "environment": "staging"})
        self.assertEqual(ch[3]["undo"]["payload"]["target_synonym"], "maxi dress,long dress")
        self.assertFalse(ch[5]["payload"]["enabled"])
        self.assertTrue(ch[5]["undo"]["payload"]["enabled"])

    def test_creates(self):
        _, ch = plan()
        self.assertEqual(ch[1]["payload"]["source_synonym"], "t-shirt")  # lower-cased and trimmed
        self.assertEqual(ch[1]["payload"]["target_synonym"], "tshirt,t shirt")
        self.assertEqual(ch[2]["payload"]["source_synonym"], "kids,children,toddler")
        self.assertEqual(ch[2]["payload"]["target_synonym"], "")
        self.assertTrue(ch[2]["payload"]["group_synonym"])
        self.assertEqual(ch[1]["undo"]["tool"], "delete_synonym")
        self.assertIn("also expands 'tshirt'", ch[11]["warnings"][0])
        self.assertIn("maps the other way", ch[12]["warnings"][0])

    def test_blocked_changes(self):
        _, ch = plan()
        for n, text in [(8, "No-op"), (9, "Duplicate of synonym 105"), (10, "enable that one instead"),
                        (13, "more than 3 words"), (14, "quote character"), (15, "at least one target"),
                        (16, "at least two different terms"), (17, "No change"),
                        (18, "Only 'User Created'"), (19, "already enabled"), (20, "isn't in the user synonym list"),
                        (21, "isn't in the user synonym list"), (22, "Unknown action"), (23, "two_way must be"),
                        (24, "Running experiment 'Fleece ranking test'"), (7, "already changes synonym 102")]:
            self.assertEqual(ch[n]["status"], "blocked", n)
            self.assertTrue(problem(ch[n], text), (n, ch[n]["problems"]))
        # A completed experiment doesn't block.
        self.assertEqual(ch[2]["status"], "planned")

    def test_batches_respect_the_cap_and_separate_deletes(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        out, _ = plan()
        for b in out["batches"]:
            self.assertLessEqual(len(b["changes"]), rules["max_changes_per_batch"])
            if b["kind"] != "changes":
                self.assertEqual(len(b["changes"]), 1)
        self.assertEqual([b["kind"] for b in out["batches"]], ["changes", "delete"])
        with tempfile.TemporaryDirectory() as tmp:
            many = {"account_name": "a", "changes": [{"action": "create", "source": f"term{i}", "targets": [f"t{i}"]}
                                                     for i in range(rules["max_changes_per_batch"] + 3)]}
            path = Path(tmp) / "many.json"
            path.write_text(json.dumps(many), encoding="utf-8")
            r, o, _ = run("--request", path, "--existing", FX / "existing.json")
        self.assertEqual([len(b["changes"]) for b in o["batches"]], [rules["max_changes_per_batch"], 3])

    def test_user_modified_delete_is_a_revert(self):
        out, ch = plan("request_revert.json")
        c = ch[1]
        self.assertEqual((c["status"], c["kind"]), ("planned", "revert"))
        self.assertIn("re-enabled", c["warnings"][0])
        self.assertIn("manual", c["undo"])
        self.assertEqual(c["payload"]["site_group_id"], "12")
        self.assertEqual(out["batches"], [{"kind": "revert", "changes": [1], "batch": 1}])

    def test_qa_files_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--request", str(FX / "request.json"), "--existing",
                                str(FX / "existing.json"), "--qa-dir", "qa", "--out", "plan.json"],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            qa = sorted(p.name for p in (Path(tmp) / "qa").iterdir())
            saved = json.loads((Path(tmp) / "plan.json").read_text(encoding="utf-8"))
            first = json.loads((Path(tmp) / "qa" / "change-1.json").read_text(encoding="utf-8"))
        self.assertEqual(qa, ["change-1.json", "change-11.json", "change-12.json", "change-2.json",
                              "change-24.json", "change-3.json", "change-4.json"])
        self.assertEqual(first, {"type": "synonym", "id": None, "source": "t-shirt", "targets": ["tshirt", "t shirt"],
                                 "two_way": False})
        self.assertEqual(saved, json.loads(r.stdout))

    def test_no_editor_emails_in_output(self):
        r, _, written = run("--request", FX / "request.json", "--existing", FX / "existing.json")
        self.assertNotIn("editor@", r.stdout)
        self.assertEqual(written, [])  # nothing written without --out or --qa-dir

    def test_errors(self):
        r, out, _ = run("--request", FX / "request.json", "--existing", FX / "error_accounts.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't repeated", out["error"])
        self.assertNotIn("beta_store", r.stdout)
        r, out, _ = run("--request", FX / "missing.json", "--existing", FX / "existing.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't read it as JSON", out["error"])
        with tempfile.TemporaryDirectory() as tmp:
            for body, text in [({"changes": []}, "account_name"), ({"account_name": "a"}, "'changes' list"),
                               ({"account_name": "a", "environment": "test", "changes": []}, "environment"),
                               ({"account_name": "a", "changes": ["x"]}, "isn't an object")]:
                path = Path(tmp) / "bad.json"
                path.write_text(json.dumps(body), encoding="utf-8")
                r, out, _ = run("--request", path, "--existing", FX / "existing.json")
                self.assertEqual(r.returncode, 1, body)
                self.assertIn(text, out["error"])
            path = Path(tmp) / "nolist.json"
            path.write_text(json.dumps({"success": True, "data": "nope"}), encoding="utf-8")
            r, out, _ = run("--request", FX / "request.json", "--existing", path)
            self.assertEqual(r.returncode, 1)
            self.assertIn("no list of records", out["error"])

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
