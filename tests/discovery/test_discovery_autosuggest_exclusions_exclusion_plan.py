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


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        written = sorted(p.name for p in Path(tmp).iterdir())
    return r, written


def plan(*extra, request=FX / "request.json"):
    r, _ = run("plan", "--request", request, "--rules", FX / "rules_before.json", "--suggestions",
               FX / "suggestions_before.json", "--queries", FX / "queries.json", "--account", "acme", *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def write(tmp, name, obj):
    p = Path(tmp) / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


class PlanTest(unittest.TestCase):
    def test_every_change_has_payload_before_after_and_undo(self):
        out = plan()
        kinds = [(c["kind"], c["rule_id"]) for c in out["changes"]]
        self.assertEqual(kinds, [("disable", 101), ("enable", 102), ("delete", 105), ("disable", 103),
                                 ("update", 104), ("create", None), ("enable", None)])
        for c in out["changes"]:
            self.assertIn(c["tool"], ("create_autosuggest_exclusion_rule", "update_autosuggest_exclusion_rule",
                                      "delete_autosuggest_exclusion_rule"))
            self.assertEqual((c["payload"]["account_name"], c["payload"]["environment"]), ("acme", "staging"))
            self.assertIn("before", c)
            self.assertIn("after", c)
            self.assertIn("tool", c["undo"])
            self.assertIn("payload", c["undo"])

    def test_new_rules_are_created_disabled_and_enabled_in_a_live_batch(self):
        out = plan()
        create = next(c for c in out["changes"] if c["kind"] == "create")
        enable = next(c for c in out["changes"] if c.get("depends_on") == create["id"])
        self.assertIs(create["payload"]["enabled"], False)
        self.assertEqual(create["live_impact"], "no live impact")
        self.assertEqual(create["payload"]["keywords"], ["dress fabric", "dress color", "dress", "xs", "sale*"])
        self.assertEqual(create["undo"]["tool"], "delete_autosuggest_exclusion_rule")
        self.assertEqual((enable["live_impact"], enable["payload"]["enabled"]), ("live", True))
        self.assertEqual([b["live_impact"] for b in out["batches"]], ["no live impact", "live", "irreversible"])

    def test_removals_and_deletes(self):
        out = plan()
        by_rule = {c["rule_id"]: c for c in out["changes"] if c["rule_id"]}
        # Unexcluding a rule's only keyword disables it rather than leaving it empty or deleting it.
        self.assertEqual((by_rule[103]["kind"], by_rule[103]["payload"]["enabled"]), ("disable", False))
        self.assertEqual(by_rule[104]["payload"]["keywords"], ["diameter"])
        self.assertEqual(by_rule[104]["undo"]["payload"]["keywords"], ["diameter", "zz top"])
        delete = by_rule[105]
        self.assertTrue(delete["separate_yes"])
        self.assertEqual(delete["undo"]["tool"], "create_autosuggest_exclusion_rule")
        last = out["batches"][-1]
        self.assertEqual((last["live_impact"], last["changes"]), ("irreversible", [delete["id"]]))
        self.assertIn("PERMANENTLY DELETE", last["confirm"])
        self.assertEqual(out["may_reappear"], ["fake brand", "northwind outlet", "scharf", "zz top"])

    def test_skips(self):
        why = [s["why"] for s in plan()["skipped"]]
        for text in ("rule 104 is already enabled", "rule 999 isn't in the rules", "no exclusion rule contains 'nothing here'",
                     "already excluded by enabled rule 101", "already in disabled rule 102"):
            self.assertTrue(any(text in w for w in why), text)

    def test_warnings_for_broad_or_odd_keywords(self):
        out = plan()
        create = next(c for c in out["changes"] if c["kind"] == "create")
        text = " ".join(w["warning"] for w in create["warnings"])
        self.assertIn("'dress' is itself a search with 1200 sessions", text)
        self.assertEqual(create["warnings"][0]["priority"], "high")
        self.assertIn("'dress' is a word in", text)
        self.assertIn("'xs' is very short", text)
        self.assertIn("'sale*' contains a wildcard", text)
        self.assertIn("Read the 4 warning(s) first", out["batches"][0]["confirm"])

    def test_preview(self):
        dr = plan()["preview"]["dr"]
        self.assertEqual(dr["hidden"], ["dress", "dress color", "dress fabric"])
        self.assertEqual(dr["after_expected"], ["black dress", "dress length", "red dress"])

    def test_batch_cap_and_rule_split(self):
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
        self.assertTrue(all(len(b["changes"]) <= cap for b in out["batches"]))
        rules ={"success": True, "data": [{"id": i, "name": f"r{i}", "keywords": [f"k{i}"], "enabled": True}
                                           for i in range(cap + 3)]}
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", [{"action": "disable", "rule_id": i} for i in range(cap + 3)])
            rf = write(tmp, "rules.json", rules)
            r, _ = run("plan", "--request", req, "--rules", rf, "--account", "acme")
        out = json.loads(r.stdout)
        self.assertEqual([len(b["changes"]) for b in out["batches"]], [cap, 3])
        self.assertIn("preview_note", out)

    def test_add_to_existing_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", {"add_to_rule_id": 104, "changes": [{"action": "exclude", "keyword": "skirt colors"}]})
            out = plan(request=req)
            c = out["changes"][0]
            self.assertEqual((c["kind"], c["rule_id"], c["live_impact"]), ("update", 104, "live"))
            self.assertEqual(c["payload"]["keywords"], ["diameter", "zz top", "skirt colors"])
            self.assertEqual(c["undo"]["payload"]["keywords"], ["diameter", "zz top"])
            req = write(tmp, "req2.json", {"add_to_rule_id": 104, "changes": [
                {"action": "exclude", "keyword": "skirt colors"}, {"action": "disable", "rule_id": 104}]})
            r, _ = run("plan", "--request", req, "--rules", FX / "rules_before.json", "--account", "acme")
            self.assertEqual(r.returncode, 1)
            self.assertIn("already has another change", json.loads(r.stdout)["error"])

    def test_one_change_per_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = write(tmp, "req.json", [{"action": "disable", "rule_id": 104}, {"action": "unexclude", "keyword": "zz top"}])
            out = plan(request=req)
        self.assertEqual([c["kind"] for c in out["changes"]], ["disable"])
        self.assertTrue(any("rule-level change" in s["why"] for s in out["skipped"]))

    def test_production_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.json"
            r, written = run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json",
                             "--account", "acme", "--environment", "production", "--out", out_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            saved = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(written, [])
        self.assertEqual(saved["environment"], "production")
        self.assertTrue(all(c["payload"]["environment"] == "production" for c in saved["changes"]))
        self.assertNotIn("editor@example.test", r.stdout)


class VerifyTest(unittest.TestCase):
    def test_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json", "--account", "acme",
                "--out", p)
            r, _ = run("verify", "--plan", p, "--rules", FX / "rules_after.json", "--suggestions",
                       FX / "suggestions_after.json")
            out = json.loads(r.stdout)
            status = {x["id"]: x["status"] for x in out["results"]}
            self.assertEqual(status["C1"], "in place")
            self.assertEqual(status["C3"], "in place")          # rule 105 is gone
            self.assertEqual(status["C4"], "in place, still syncing")
            self.assertEqual(status["C5"], "not in place")      # rule 104 still has "zz top"
            self.assertEqual((status["C6"], status["C7"]), ("in place", "in place"))
            self.assertFalse(out["all_in_place"])
            self.assertEqual(out["still_suggested"], [{"prefix": "dr", "suggestion": "dress color"}])
            self.assertIn("few minutes", out["note"])
            r, _ = run("verify", "--plan", p, "--rules", FX / "rules_after.json", "--applied", "C1,C2")
            out = json.loads(r.stdout)
            self.assertEqual([x["id"] for x in out["results"]], ["C1", "C2"])
            self.assertTrue(out["all_in_place"])


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
                r, _ = run("plan", "--request", req, "--rules", FX / "rules_before.json", "--account", "acme")
                self.assertEqual(r.returncode, 1, text)
                self.assertIn(text, json.loads(r.stdout)["error"])
            bad_rules = write(tmp, "rules.json", {"success": True, "data": [{"id": "x", "keywords": []}]})
            r, _ = run("plan", "--request", FX / "request.json", "--rules", bad_rules, "--account", "acme")
            self.assertIn("no numeric id", json.loads(r.stdout)["error"])
            bad_sugg = write(tmp, "s.json", {"dr": "dress"})
            r, _ = run("plan", "--request", FX / "request.json", "--rules", FX / "rules_before.json",
                       "--suggestions", bad_sugg, "--account", "acme")
            self.assertIn("one list per prefix", json.loads(r.stdout)["error"])
            r, _ = run("plan", "--request", Path(tmp) / "missing.json", "--rules", FX / "rules_before.json",
                       "--account", "acme")
            self.assertIn("can't read it", json.loads(r.stdout)["error"])
            r, _ = run("verify", "--plan", FX / "queries.json", "--rules", FX / "rules_after.json")
            self.assertIn("not a plan", json.loads(r.stdout)["error"])

    def test_account_list_errors_are_not_repeated(self):
        r, _ = run("plan", "--request", FX / "request.json", "--rules", FX / "denied.json", "--account", "acme")
        self.assertEqual(r.returncode, 1)
        err = json.loads(r.stdout)["error"]
        self.assertIn("it isn't repeated", err)
        self.assertNotIn("gamma", err)

    def test_help(self):
        r, _ = run("--help")
        self.assertEqual(r.returncode, 0)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        self.assertEqual(set(RULES) - {"about", "notes"}, set(RULES["notes"]))


if __name__ == "__main__":
    unittest.main()
