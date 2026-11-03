"""Tests for discovery-synonym-fixer's synonym_plan.py, which plans synonym writes before anything is written
and checks them after. Fixtures are synthetic."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-synonym-fixer"
SCRIPT = SKILL / "scripts/synonym_plan.py"
FX = ROOT / "tests/fixtures/discovery/synonym_fixer"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
CTX = ("--account", "acme_outdoors", "--environment", "staging")
CHANGE_KEYS = {"n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings"}


def run(*args, env=None):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, env=env)
        written = sorted(p.name for p in Path(tmp).iterdir())
    return r, (json.loads(r.stdout) if r.stdout.strip() else None), written


def plan(request="request.json", *extra, ctx=CTX):
    r, out, _ = run("plan", *ctx, "--request", FX / request, "--existing", FX / "existing.json",
                    "--experiments", FX / "experiments.json", *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return out, {c["n"]: c for c in out["changes"]}


def problem(change, text):
    return any(text in p for p in change["problems"])


def temp_json(tmp, name, body):
    path = Path(tmp) / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


class PlanShapeTest(unittest.TestCase):
    def test_follows_the_shared_plan_shape(self):
        out, ch = plan()
        self.assertEqual(set(out), {"ok", "account", "environment", "site_group_id", "changes", "batches"})
        self.assertEqual((out["account"], out["environment"], out["site_group_id"]), ("acme_outdoors", "staging", None))
        for c in ch.values():
            self.assertEqual(set(c), CHANGE_KEYS, c["n"])
            self.assertIn(c["status"], ("ready", "blocked", "no_change"))
            self.assertIn(c["kind"], ("create", "update", "enable", "disable", "delete"))
            self.assertIn(c["live_impact"], ("none", "live"))
            self.assertIsInstance(c["undo"], list)
        self.assertEqual(list(ch), list(range(1, len(ch) + 1)))

    def test_every_ready_change_has_payload_before_after_and_undo(self):
        _, ch = plan()
        for c in ch.values():
            if c["status"] != "ready":
                continue
            self.assertTrue(c["tool"] and c["payload"], c["n"])
            if c["kind"] != "create":
                self.assertIsNotNone(c["before"], c["n"])
            if c["kind"] != "delete":
                self.assertIsNotNone(c["after"], c["n"])
            self.assertTrue(c["undo"], c["n"])
            for step in c["undo"]:
                self.assertEqual(set(step), {"tool", "payload"})

    def test_update_payloads_are_complete(self):
        # update_synonym defaults to one-way and enabled, so every update sends all four fields.
        _, ch = plan()
        for n in (5, 6, 7):
            self.assertTrue(set(ch[n]["payload"]) >= {"synonym_id", "source_synonym", "target_synonym",
                                                      "group_synonym", "enabled"}, n)
        self.assertEqual(ch[6]["payload"], {"synonym_id": 103, "source_synonym": "sneakers,trainers,runners",
                                            "target_synonym": "", "group_synonym": True, "enabled": True,
                                            "account_name": "acme_outdoors", "environment": "staging"})
        self.assertEqual(ch[5]["undo"][0]["payload"]["target_synonym"], "maxi dress,long dress")
        self.assertFalse(ch[7]["payload"]["enabled"])
        self.assertTrue(ch[7]["undo"][0]["payload"]["enabled"])


class CreateTest(unittest.TestCase):
    def test_creates_are_switched_off_then_switched_on_separately(self):
        _, ch = plan()
        create, enable = ch[1], ch[2]
        self.assertEqual((create["kind"], create["tool"], create["live_impact"]), ("create", "create_synonym", "none"))
        self.assertFalse(create["payload"]["enabled"])
        self.assertEqual(create["payload"]["source_synonym"], "t-shirt")  # lower-cased and trimmed
        self.assertEqual(create["payload"]["target_synonym"], "tshirt,t shirt")
        self.assertEqual(create["undo"][0]["tool"], "delete_synonym")
        self.assertEqual((enable["kind"], enable["tool"], enable["live_impact"]), ("enable", "update_synonym", "live"))
        self.assertTrue(enable["payload"]["enabled"])
        self.assertEqual(enable["payload"]["synonym_id"], "<id from the create change>")
        self.assertIn("created by change 1", enable["target"])
        self.assertFalse(enable["undo"][0]["payload"]["enabled"])
        self.assertEqual(ch[3]["payload"]["source_synonym"], "kids,children,toddler")
        self.assertTrue(ch[3]["payload"]["group_synonym"])

    def test_create_left_off_has_no_enable_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = temp_json(tmp, "r.json", {"changes": [{"action": "create", "source": "gilet", "targets": ["vest"],
                                                         "enabled": False}]})
            r, out, _ = run("plan", *CTX, "--request", req, "--existing", FX / "existing.json")
        self.assertEqual([c["kind"] for c in out["changes"]], ["create"])
        self.assertEqual(out["batches"], [[1]])

    def test_blocked_create_gets_no_enable_step(self):
        _, ch = plan()
        self.assertEqual((ch[10]["kind"], ch[10]["status"]), ("create", "blocked"))
        self.assertEqual(ch[11]["kind"], "create")  # the next request, not an enable for the blocked create
        self.assertIn("also expands 'tshirt'", ch[13]["warnings"][0])
        self.assertIn("maps the other way", ch[15]["warnings"][0])


class BlockedTest(unittest.TestCase):
    def test_blocked_and_no_change(self):
        _, ch = plan()
        for n, text in [(9, "already changes synonym 102"), (10, "No-op"), (11, "Duplicate of synonym 105"),
                        (12, "enable that one instead"), (17, "more than 3 words"), (18, "quote character"),
                        (19, "at least one target"), (20, "at least two different terms"),
                        (22, "Only 'User Created'"), (23, "already enabled"), (24, "isn't in the user synonym list"),
                        (25, "isn't in the user synonym list"), (26, "Unknown action"),
                        (27, "Request change 23: two_way must be"), (28, "Running experiment 'Fleece ranking test'")]:
            self.assertEqual(ch[n]["status"], "blocked", n)
            self.assertTrue(problem(ch[n], text), (n, ch[n]["problems"]))
        self.assertEqual(ch[21]["status"], "no_change")
        self.assertTrue(problem(ch[21], "No change"))
        # A completed experiment mentioning "kids" doesn't block.
        self.assertEqual(ch[3]["status"], "ready")

    def test_running_statuses_case_and_missing_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = temp_json(tmp, "r.json", {"changes": [{"action": "create", "source": "gilet", "targets": ["vest"]},
                                                        {"action": "create", "source": "scarf", "targets": ["snood"]}]})
            exps = temp_json(tmp, "e.json", {"data": [{"name": "Upper", "status": "Running", "queries": ["gilet"]},
                                                      {"name": "No status", "queries": ["scarf"]}]})
            r, out, _ = run("plan", *CTX, "--request", req, "--existing", FX / "existing.json", "--experiments", exps)
        self.assertEqual([c["status"] for c in out["changes"]], ["blocked", "blocked"])
        self.assertTrue(problem(out["changes"][0], "'Upper'"))
        self.assertTrue(problem(out["changes"][1], "'No status'"))


class BatchTest(unittest.TestCase):
    def test_batches_cap_ready_changes_and_separate_switch_ons_and_deletes(self):
        out, ch = plan()
        self.assertEqual(out["batches"], [[1, 3, 5, 7, 13, 15], [2], [4], [6], [14], [16], [8]])
        batched = [n for b in out["batches"] for n in b]
        self.assertEqual(sorted(batched), sorted(n for n, c in ch.items() if c["status"] == "ready"))
        for b in out["batches"]:
            self.assertLessEqual(len(b), RULES["max_changes_per_batch"])
            if any(ch[n]["kind"] in ("enable", "delete") for n in b):
                self.assertEqual(len(b), 1)

    def test_cap_counts_only_ready_changes(self):
        cap = RULES["max_changes_per_batch"]
        changes = [{"action": "create", "source": f"term{i}", "targets": [f"t{i}"], "enabled": False}
                   for i in range(cap + 3)]
        changes.insert(1, {"action": "create", "source": "corset", "targets": ["corset"]})  # blocked: no-op
        with tempfile.TemporaryDirectory() as tmp:
            req = temp_json(tmp, "many.json", {"changes": changes})
            r, out, _ = run("plan", *CTX, "--request", req, "--existing", FX / "existing.json")
        self.assertEqual([len(b) for b in out["batches"]], [cap, 3])
        self.assertNotIn(2, [n for b in out["batches"] for n in b])

    def test_delete_of_an_enabled_synonym_undoes_switched_off_then_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = temp_json(tmp, "r.json", {"changes": [{"action": "delete", "id": 105}]})
            r, out, _ = run("plan", *CTX, "--request", req, "--existing", FX / "existing.json")
        c = out["changes"][0]
        self.assertEqual((c["kind"], c["live_impact"]), ("delete", "live"))
        self.assertEqual([u["tool"] for u in c["undo"]], ["create_synonym", "update_synonym"])
        self.assertFalse(c["undo"][0]["payload"]["enabled"])
        self.assertTrue(c["undo"][1]["payload"]["enabled"])

    def test_user_modified_delete_is_a_revert(self):
        out, ch = plan("request_revert.json", "--site-group-id", "12",
                       ctx=("--account", "acme_outdoors", "--environment", "production"))
        c = ch[1]
        self.assertEqual((c["status"], c["kind"], c["undo"]), ("ready", "delete", []))
        self.assertIn("re-enabled", c["warnings"][0])
        self.assertEqual(c["payload"]["site_group_id"], "12")
        self.assertEqual(out["site_group_id"], "12")
        self.assertEqual(out["batches"], [[1]])


class OptionsTest(unittest.TestCase):
    def test_environment_and_account_are_required(self):
        for args in (("--account", "a"), ("--environment", "staging"), ("--account", "a", "--environment", "test")):
            r, _, _ = run("plan", *args, "--request", FX / "request.json", "--existing", FX / "existing.json")
            self.assertEqual(r.returncode, 2, args)

    def test_request_context_must_match_the_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = temp_json(tmp, "r.json", {"environment": "production", "changes": []})
            r, out, _ = run("plan", *CTX, "--request", req, "--existing", FX / "existing.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--environment", out["error"])

    def test_output_is_the_same_whatever_the_hash_seed(self):
        outputs = set()
        for seed in ("1", "2", "3", "4"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            r, _, _ = run("plan", *CTX, "--request", FX / "request.json", "--existing", FX / "existing.json",
                          "--experiments", FX / "experiments.json", env=env)
            outputs.add(r.stdout)
        self.assertEqual(len(outputs), 1)


class FilesTest(unittest.TestCase):
    def test_qa_files_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "plan", *CTX, "--request", str(FX / "request.json"),
                                "--existing", str(FX / "existing.json"), "--qa-dir", "qa", "--out", "plan.json"],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            qa = sorted(p.name for p in (Path(tmp) / "qa").iterdir())
            saved = json.loads((Path(tmp) / "plan.json").read_text(encoding="utf-8"))
            first = json.loads((Path(tmp) / "qa" / "change-1.json").read_text(encoding="utf-8"))
        # No --experiments here, so the "fleece" create (change 28) isn't blocked and gets a file too.
        self.assertEqual(qa, ["change-1.json", "change-13.json", "change-15.json", "change-28.json", "change-3.json",
                              "change-5.json", "change-6.json"])
        self.assertEqual(first, {"type": "synonym", "id": None, "source": "t-shirt", "targets": ["tshirt", "t shirt"],
                                 "two_way": False})
        self.assertEqual(saved, json.loads(r.stdout))

    def test_unwritable_out_fails_cleanly(self):
        r, out, _ = run("plan", *CTX, "--request", FX / "request.json", "--existing", FX / "existing.json",
                        "--out", "/nonexistent-dir/plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't write it", out["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_no_editor_emails_in_output(self):
        r, _, written = run("plan", *CTX, "--request", FX / "request.json", "--existing", FX / "existing.json")
        self.assertNotIn("editor@", r.stdout)
        self.assertEqual(written, [])  # nothing written without --out or --qa-dir

    def test_errors(self):
        r, out, _ = run("plan", *CTX, "--request", FX / "request.json", "--existing", FX / "error_accounts.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't repeated", out["error"])
        self.assertNotIn("beta_store", r.stdout)
        r, out, _ = run("plan", *CTX, "--request", FX / "missing.json", "--existing", FX / "existing.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't read it as JSON", out["error"])
        with tempfile.TemporaryDirectory() as tmp:
            # Any error mentioning an account is suppressed, even without a list.
            err = temp_json(tmp, "err.json", {"success": False, "error": "Unknown account: secret_brand"})
            r, out, _ = run("plan", *CTX, "--request", FX / "request.json", "--existing", err)
            self.assertIn("isn't repeated", out["error"])
            self.assertNotIn("secret_brand", r.stdout)
            for body, text in [({}, "'changes' list"), ({"changes": ["x"]}, "isn't an object")]:
                path = temp_json(tmp, "bad.json", body)
                r, out, _ = run("plan", *CTX, "--request", path, "--existing", FX / "existing.json")
                self.assertEqual(r.returncode, 1, body)
                self.assertIn(text, out["error"])
            path = temp_json(tmp, "nolist.json", {"success": True, "data": "nope"})
            r, out, _ = run("plan", *CTX, "--request", FX / "request.json", "--existing", path)
            self.assertEqual(r.returncode, 1)
            self.assertIn("no list of records", out["error"])


class VerifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r, out, _ = run("plan", *CTX, "--request", FX / "request.json", "--existing", FX / "existing.json",
                        "--experiments", FX / "experiments.json")
        cls.plan = temp_json(cls.tmp.name, "plan.json", out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verify(self, *extra, readback=FX / "readback.json"):
        r, out, _ = run("verify", "--plan", self.plan, "--readback", readback, *extra)
        return r, out

    def test_a_site_not_found_error_stops_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = temp_json(tmp, "site.json", {"success": False, "error": "Site group 77 not found"})
            r, out = self.verify(readback=site)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("gone", json.dumps(out))

    def test_reports_in_place_not_in_place_and_gone(self):
        r, out = self.verify()
        self.assertEqual(r.returncode, 0, r.stderr)
        res = {x["n"]: x for x in out["results"]}
        self.assertEqual({n: x["result"] for n, x in res.items()},
                         {1: "in_place", 2: "in_place", 3: "in_place", 4: "not_in_place", 5: "in_place",
                          6: "in_place", 7: "not_in_place", 8: "gone", 13: "gone", 14: "gone", 15: "gone", 16: "gone"})
        self.assertTrue(res[8]["ok"])  # a delete should be gone
        self.assertEqual(res[1]["new_id"], 2001)
        self.assertFalse(out["all_ok"])
        self.assertNotIn("editor@", r.stdout)

    def test_only_some_changes(self):
        _, out = self.verify("--changes", "1,2,5,8")
        self.assertEqual([x["n"] for x in out["results"]], [1, 2, 5, 8])
        self.assertTrue(out["all_ok"])

    def test_not_found_read_back_counts_as_gone_other_errors_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            nf = temp_json(tmp, "nf.json", {"success": False, "error": "Synonym 104 not found"})
            _, out = self.verify("--changes", "8", readback=nf)
            self.assertEqual(out["results"][0]["result"], "gone")
            # "Account not found" is about the account, not the synonym: it stops verify, never counts as gone.
            acct = temp_json(tmp, "acct.json", {"success": False, "error": "Account not found: other_brand"})
            r, out = self.verify("--changes", "8", readback=acct)
            self.assertEqual(r.returncode, 1)
            self.assertIn("isn't repeated", out["error"])
            self.assertIn("can't be checked", out["error"])
            self.assertNotIn("other_brand", r.stdout)
            bad = temp_json(tmp, "bad.json", {"success": False, "error": "Service unavailable"})
            r, out = self.verify(readback=bad)
            self.assertEqual(r.returncode, 1)
            self.assertIn("can't be checked", out["error"])
            notplan = temp_json(tmp, "np.json", {"hello": 1})
            r, out, _ = run("verify", "--plan", notplan, "--readback", FX / "readback.json")
            self.assertEqual(r.returncode, 1)
            self.assertIn("isn't a synonym plan", out["error"])
        r, _, _ = run("verify", "--plan", self.plan, "--readback", FX / "readback.json", "--changes", "x")
        self.assertEqual(r.returncode, 2)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        self.assertEqual(set(RULES) - {"about", "notes"}, set(RULES["notes"]))


if __name__ == "__main__":
    unittest.main()
