"""Tests for discovery-autosuggest-exclusions' exclusion_plan.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-autosuggest-exclusions"
SCRIPT = SKILL / "scripts/exclusion_plan.py"
FX = ROOT / "tests/fixtures/discovery/autosuggest_exclusions"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
CHANGE_KEYS = {"n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings"}


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        written = sorted(p.name for p in Path(tmp).iterdir())
    return r, written


def plan(*extra, request=FX / "request.json", env="staging"):
    r, _ = run("plan", "--request", request, "--rules", FX / "rules_before.json", "--suggestions",
               FX / "suggestions_before.json", "--queries", FX / "queries.json", "--account", "acme",
               "--environment", env, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def write(tmp, name, obj):
    p = Path(tmp) / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def by_status(out, status):
    return [c for c in out["changes"] if c["status"] == status]


class PlanTest(unittest.TestCase):
    def test_plan_file_shape(self):
        out = plan()
        self.assertEqual((out["account"], out["environment"], out["site_group_id"]), ("acme", "staging", None))
        self.assertEqual([c["n"] for c in out["changes"]], list(range(1, len(out["changes"]) + 1)))
        for c in out["changes"]:
            self.assertTrue(CHANGE_KEYS <= set(c), c)
            self.assertIn(c["status"], ("ready", "blocked", "no_change"))
            self.assertIn(c["live_impact"], ("none", "live"))
            self.assertIsInstance(c["undo"], list)
        ready = [(c["kind"], c["rule_id"]) for c in by_status(out, "ready")]
        self.assertEqual(ready, [("disable", 101), ("enable", 102), ("delete", 105), ("disable", 103),
                                 ("update", 104), ("create", None), ("enable", None)])
        for c in by_status(out, "ready"):
            self.assertIn(c["tool"], ("create_autosuggest_exclusion_rule", "update_autosuggest_exclusion_rule",
                                      "delete_autosuggest_exclusion_rule"))
            self.assertEqual((c["payload"]["account_name"], c["payload"]["environment"]), ("acme", "staging"))
            self.assertTrue(c["undo"] and all({"tool", "payload"} <= set(u) for u in c["undo"]))
        self.assertEqual(out["counts"], {"ready": 7, "blocked": 2, "no_change": 3})

    def test_blocked_and_no_change_replace_skipped(self):
        out = plan()
        self.assertNotIn("skipped", out)
        blocked = " ".join(p for c in by_status(out, "blocked") for p in c["problems"])
        no_change = " ".join(p for c in by_status(out, "no_change") for p in c["problems"])
        self.assertIn("rule 999 isn't in the rules", blocked)
        self.assertIn("already in disabled rule 102", blocked)
        for text in ("rule 104 is already enabled", "no exclusion rule contains 'nothing here'",
                     "already excluded by enabled rule 101"):
            self.assertIn(text, no_change)
        batched = {n for b in out["batches"] for n in b}
        self.assertFalse(batched & {c["n"] for c in out["changes"] if c["status"] != "ready"})

    def test_new_rules_are_created_disabled_and_switched_on_alone(self):
        out = plan()
        create = next(c for c in out["changes"] if c["kind"] == "create")
        enable = next(c for c in out["changes"] if c.get("depends_on") == create["n"])
        self.assertIs(create["payload"]["enabled"], False)
        self.assertEqual(create["live_impact"], "none")
        self.assertEqual(create["payload"]["keywords"], ["dress fabric", "dress color", "dress", "xs", "sale*"])
        self.assertEqual(create["undo"][0]["tool"], "delete_autosuggest_exclusion_rule")
        self.assertEqual((enable["live_impact"], enable["payload"]["enabled"]), ("live", True))
        # Every switch-on and every delete is a batch of its own; only the rest share batches.
        for b in out["batches"]:
            kinds = [next(c for c in out["changes"] if c["n"] == n)["kind"] for n in b]
            if "enable" in kinds or "delete" in kinds:
                self.assertEqual(len(b), 1, b)
        self.assertEqual(out["batches"], [[create["n"]], [1, 7, 8], [2], [enable["n"]], [4]])

    def test_removals_and_deletes(self):
        out = plan()
        by_rule = {c["rule_id"]: c for c in by_status(out, "ready") if c["rule_id"]}
        # Unexcluding a rule's only keyword disables it rather than leaving it empty or deleting it.
        self.assertEqual((by_rule[103]["kind"], by_rule[103]["payload"]["enabled"]), ("disable", False))
        self.assertEqual(by_rule[104]["payload"]["keywords"], ["diameter"])
        self.assertEqual(by_rule[104]["undo"][0]["payload"]["keywords"], ["diameter", "zz top"])
        delete = by_rule[105]
        self.assertEqual(delete["undo"][0]["tool"], "create_autosuggest_exclusion_rule")
        self.assertEqual(out["batches"][-1], [delete["n"]])
        self.assertIn("PERMANENTLY DELETE", out["batch_confirm"][-1])
        self.assertEqual(out["may_reappear"], ["fake brand", "northwind outlet", "scharf", "zz top"])

    def test_undo_of_a_delete_recreates_disabled_then_switches_on_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = write(tmp, "rules.json", {"success": True, "data": [
                {"id": 7, "name": "On rule", "keywords": ["junk"], "enabled": True}]})
            req = write(tmp, "req.json", [{"action": "delete", "rule_id": 7}])
            r, _ = run("plan", "--request", req, "--rules", rules, "--account", "acme", "--environment", "staging")
        c = json.loads(r.stdout)["changes"][0]
        self.assertEqual(c["live_impact"], "live")
        self.assertEqual([u["tool"] for u in c["undo"]], ["create_autosuggest_exclusion_rule",
                                                          "update_autosuggest_exclusion_rule"])
        self.assertIs(c["undo"][0]["payload"]["enabled"], False)
        self.assertIs(c["undo"][1]["payload"]["enabled"], True)
        # A disabled rule's delete undo stays a single, disabled create.
        out = plan()
        delete = next(c for c in out["changes"] if c["kind"] == "delete")
        self.assertEqual(len(delete["undo"]), 1)
        self.assertIs(delete["undo"][0]["payload"]["enabled"], False)

    def test_warnings_for_broad_or_odd_keywords(self):
        out = plan()
        create = next(c for c in out["changes"] if c["kind"] == "create")
        text = " ".join(w["warning"] for w in create["warnings"])
        self.assertIn("'dress' is itself a search with 1200 sessions", text)
        self.assertEqual(create["warnings"][0]["priority"], "high")
        self.assertTrue(all(w["priority"] in ("high", "medium", "low") for w in create["warnings"]))
        self.assertIn("'dress' is a word in", text)
        self.assertIn("'xs' is very short", text)
        self.assertIn("'sale*' contains a wildcard", text)
        self.assertIn("Read the 4 warning(s) first", out["batch_confirm"][0])

    def test_preview(self):
        dr = plan()["preview"]["dr"]
        self.assertEqual(dr["hidden"], ["dress", "dress color", "dress fabric"])
        self.assertEqual(dr["after_expected"], ["black dress", "dress length", "red dress"])

    def test_batch_cap_counts_ready_changes_only_and_rules_split(self):
        n = RULES["max_keywords_per_rule"] + 5
        cap = RULES["max_changes_per_batch"]
        changes = [{"action": "exclude", "keyword": f"junk term {i}"} for i in range(n)]
        changes += [{"action": "disable", "rule_id": 101}, {"action": "enable", "rule_id": 102}]
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", {"changes": changes})
            out = plan(request=req)
        creates = [c for c in out["changes"] if c["kind"] == "create"]
        self.assertEqual([len(c["payload"]["keywords"]) for c in creates], [RULES["max_keywords_per_rule"], 5])
        self.assertEqual([c["payload"]["rule_name"] for c in creates],
                         [f"{RULES['default_rule_name']} 1", f"{RULES['default_rule_name']} 2"])
        self.assertTrue(all(len(b) <= cap for b in out["batches"]))
        rules = {"success": True, "data": [{"id": i, "name": f"r{i}", "keywords": [f"k{i}"], "enabled": True}
                                           for i in range(cap + 3)]}
        with tempfile.TemporaryDirectory() as tmp:
            # Blocked changes (unknown rules) don't use up room in a batch.
            req = write(tmp, "req.json", [{"action": "disable", "rule_id": 900 + i} for i in range(5)]
                        + [{"action": "disable", "rule_id": i} for i in range(cap + 3)])
            rf = write(tmp, "rules.json", rules)
            r, _ = run("plan", "--request", req, "--rules", rf, "--account", "acme", "--environment", "staging")
        out = json.loads(r.stdout)
        self.assertEqual([len(b) for b in out["batches"]], [cap, 3])
        self.assertEqual(len(by_status(out, "blocked")), 5)
        self.assertIn("preview_note", out)

    def test_add_to_existing_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", {"add_to_rule_id": 104, "changes": [{"action": "exclude", "keyword": "skirt colors"}]})
            out = plan(request=req)
            c = out["changes"][0]
            self.assertEqual((c["status"], c["kind"], c["rule_id"], c["live_impact"]), ("ready", "update", 104, "live"))
            self.assertEqual(c["payload"]["keywords"], ["diameter", "zz top", "skirt colors"])
            self.assertEqual(c["undo"][0]["payload"]["keywords"], ["diameter", "zz top"])
            req = write(tmp, "req2.json", {"add_to_rule_id": 104, "changes": [
                {"action": "exclude", "keyword": "skirt colors"}, {"action": "disable", "rule_id": 104}]})
            out = plan(request=req)
            self.assertEqual([(c["kind"], c["status"]) for c in out["changes"]], [("disable", "ready"), ("update", "blocked")])
            self.assertIn("already has another change", out["changes"][1]["problems"][0])

    def test_bad_add_to_rule_id_blocks_only_that_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", {"add_to_rule_id": 4242, "changes": [
                {"action": "exclude", "keyword": "skirt colors"}, {"action": "disable", "rule_id": 101}]})
            out = plan(request=req)
        self.assertEqual([(c["kind"], c["status"]) for c in out["changes"]], [("disable", "ready"), ("update", "blocked")])
        self.assertIn("add_to_rule_id 4242 isn't in the rules", out["changes"][1]["problems"][0])
        self.assertEqual(out["changes"][1]["keywords"], ["skirt colors"])
        self.assertEqual(out["batches"], [[1]])

    def test_one_change_per_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", [{"action": "disable", "rule_id": 104}, {"action": "unexclude", "keyword": "zz top"}])
            out = plan(request=req)
        self.assertEqual([(c["kind"], c["status"]) for c in out["changes"]], [("disable", "ready"), ("update", "blocked")])
        self.assertIn("rule-level change", out["changes"][1]["problems"][0])

    def test_production_site_group_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.json"
            r, written = run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json",
                             "--account", "acme", "--environment", "production", "--site-group-id", "7",
                             "--out", out_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            saved = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(written, [])
        self.assertEqual((saved["environment"], saved["site_group_id"]), ("production", "7"))
        self.assertIn("doesn't limit a rule to one site", saved["site_group_id_note"])
        for c in by_status(saved, "ready"):
            self.assertEqual((c["payload"]["environment"], c["payload"]["site_group_id"]), ("production", "7"))
            self.assertTrue(all(u["payload"]["site_group_id"] == "7" for u in c["undo"]))
        self.assertNotIn("editor@example.test", r.stdout)

    def test_account_and_environment_are_required(self):
        for missing in ("--account", "--environment"):
            args = ["plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json",
                    "--account", "acme", "--environment", "staging"]
            i = args.index(missing)
            del args[i:i + 2]
            r, _ = run(*args)
            self.assertEqual(r.returncode, 2, missing)
            self.assertIn(missing, r.stderr)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = Path(self.tmp.name) / "plan.json"
        r, _ = run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json", "--account", "acme",
                   "--environment", "staging", "--out", self.plan)
        assert r.returncode == 0, r.stdout

    def tearDown(self):
        self.tmp.cleanup()

    def test_verify(self):
        r, _ = run("verify", "--plan", self.plan, "--rules", FX / "rules_after.json", "--suggestions",
                   FX / "suggestions_after.json", "--created", "11=106")
        out = json.loads(r.stdout)
        res = {x["n"]: x for x in out["results"]}
        self.assertEqual(sorted(res), [1, 2, 4, 7, 8, 11, 12])     # ready changes only
        self.assertEqual(res[1]["status"], "in_place")
        self.assertEqual(res[4]["status"], "gone")                 # rule 105 is gone from the full list
        self.assertEqual((res[7]["status"], res[7]["syncing"]), ("in_place", True))
        self.assertEqual(res[8]["status"], "not_in_place")         # rule 104 still has "zz top"
        self.assertEqual((res[11]["status"], res[12]["status"], res[12]["rule_id"]), ("in_place", "in_place", 106))
        self.assertFalse(out["all_in_place"])
        self.assertEqual(out["still_suggested"], [{"prefix": "dr", "suggestion": "dress color"}])
        self.assertIn("few minutes", out["note"])
        r, _ = run("verify", "--plan", self.plan, "--rules", FX / "rules_after.json", "--applied", "1,2")
        out = json.loads(r.stdout)
        self.assertEqual([x["n"] for x in out["results"]], [1, 2])
        self.assertTrue(out["all_in_place"])

    def test_new_rules_are_matched_by_id_never_by_name(self):
        # Without the create's returned ID, a rule with the same name doesn't count.
        r, _ = run("verify", "--plan", self.plan, "--rules", FX / "rules_after.json", "--applied", "11,12")
        res = {x["n"]: x for x in json.loads(r.stdout)["results"]}
        self.assertEqual((res[11]["status"], res[12]["status"]), ("not_in_place", "not_in_place"))
        self.assertIn("--created 11=ID", res[12]["note"])
        # The wrong ID (an existing rule with other keywords) doesn't count either.
        r, _ = run("verify", "--plan", self.plan, "--rules", FX / "rules_after.json", "--applied", "11,12",
                   "--created", "11=104")
        res = {x["n"]: x for x in json.loads(r.stdout)["results"]}
        self.assertEqual(res[11]["status"], "not_in_place")

    def test_deletes_need_a_read_back_and_not_found_counts_as_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            detail = write(tmp, "detail.json", {"success": True, "data": {"id": 101, "name": "Competitors",
                                                                          "keywords": ["x"], "enabled": False}})
            r, _ = run("verify", "--plan", self.plan, "--rules", detail, "--applied", "4")
            res = json.loads(r.stdout)["results"][0]
            self.assertEqual(res["status"], "not_in_place")
            self.assertIn("no read-back covers rule 105", res["note"])
            missing = write(tmp, "missing.json", {"result": {"success": False, "error": "Rule 105 not found"}})
            r, _ = run("verify", "--plan", self.plan, "--rules", missing, "--applied", "4")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual(json.loads(r.stdout)["results"][0]["status"], "gone")
            # An unknown account isn't a deleted rule: it stops, without repeating the error.
            acct = write(tmp, "acct.json", {"success": False, "error": "Account 'acme' not found: alpha, beta"})
            r, _ = run("verify", "--plan", self.plan, "--rules", acct, "--applied", "4")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("beta", r.stdout)

    def test_bad_verify_arguments(self):
        for args, text in ((["--applied", "C1"], "comma-separated change numbers"),
                           (["--created", "11"], "expected N=ID")):
            r, _ = run("verify", "--plan", self.plan, "--rules", FX / "rules_after.json", *args)
            self.assertEqual(r.returncode, 2)
            self.assertIn(text, r.stderr)


class ErrorTest(unittest.TestCase):
    def test_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                (write(tmp, "a.json", {"changes": [{"action": "nuke"}]}), "needs 'action'"),
                (write(tmp, "b.json", {"changes": [{"action": "exclude"}]}), "needs a 'keyword'"),
                (write(tmp, "c.json", {"changes": [{"action": "delete", "rule_id": "abc"}]}), "numeric 'rule_id'"),
                (write(tmp, "d.json", {"nope": 1}), "expected {\"changes\""),
            ]
            for req, text in cases:
                r, _ = run("plan", "--request", req, "--rules", FX / "rules_before.json", "--account", "acme",
                           "--environment", "staging")
                self.assertEqual(r.returncode, 1, text)
                self.assertIn(text, json.loads(r.stdout)["error"])
            bad_rules = write(tmp, "rules.json", {"success": True, "data": [{"id": "x", "keywords": []}]})
            r, _ = run("plan", "--request", FX / "request.json", "--rules", bad_rules, "--account", "acme",
                       "--environment", "staging")
            self.assertIn("no numeric id", json.loads(r.stdout)["error"])
            bad_sugg = write(tmp, "s.json", {"dr": "dress"})
            r, _ = run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json",
                       "--suggestions", bad_sugg, "--account", "acme", "--environment", "staging")
            self.assertIn("one list per prefix", json.loads(r.stdout)["error"])
            r, _ = run("plan", "--request", Path(tmp) / "missing.json", "--rules", FX / "rules_before.json",
                       "--account", "acme", "--environment", "staging")
            self.assertIn("can't read it", json.loads(r.stdout)["error"])
            r, _ = run("verify", "--plan", FX / "queries.json", "--rules", FX / "rules_after.json")
            self.assertIn("not a plan", json.loads(r.stdout)["error"])
            old = write(tmp, "old.json", {"ok": True, "changes": [{"id": "C1", "kind": "create"}]})
            r, _ = run("verify", "--plan", old, "--rules", FX / "rules_after.json")
            self.assertIn("not a plan", json.loads(r.stdout)["error"])

    def test_unwritable_out_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json", "--account",
                       "acme", "--environment", "staging", "--out", Path(tmp) / "no-such-folder" / "plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't write the result", json.loads(r.stdout.strip().splitlines()[-1])["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_account_errors_are_never_repeated(self):
        r, _ = run("plan", "--request", FX / "request.json", "--rules", FX / "denied.json", "--account", "acme",
                   "--environment", "staging")
        self.assertEqual(r.returncode, 1)
        err = json.loads(r.stdout)["error"]
        self.assertIn("it isn't repeated", err)
        self.assertNotIn("gamma", err)
        with tempfile.TemporaryDirectory() as tmp:
            short = write(tmp, "short.json", {"success": False, "error": "Account 'x' not found. Did you mean beta?"})
            r, _ = run("plan", "--request", FX / "request.json", "--rules", short, "--account", "acme",
                       "--environment", "staging")
        err = json.loads(r.stdout)["error"]
        self.assertIn("it isn't repeated", err)
        self.assertNotIn("beta", err)

    def test_help(self):
        r, _ = run("--help")
        self.assertEqual(r.returncode, 0)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        self.assertEqual(set(RULES) - {"about", "notes"}, set(RULES["notes"]))


if __name__ == "__main__":
    unittest.main()
