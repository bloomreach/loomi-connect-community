"""Tests for facet-rule-fixer's facet_rule_plan.py. The fixtures are synthetic facet rules and experiments."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/facet-rule-fixer"
SCRIPT = SKILL / "scripts/facet_rule_plan.py"
FX = ROOT / "tests/fixtures/discovery/facet_rule_fixer"
CHANGE_KEYS = {"n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings"}


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def inputs(*extra_rule_ids):
    args = ["--rules", FX / "rules_global.json", "--rules", FX / "rules_search.json",
            "--rules", FX / "rules_category.json", "--experiments", FX / "experiments.json",
            "--attributes", FX / "attributes.json", "--categories", FX / "categories.json"]
    for i in (501, 502, 503, 504, 505, 506, *extra_rule_ids):
        args += ["--rule", f"{i}={FX / f'rule_{i}.json'}"]
    return args


def plan(changes=FX / "changes.json", *extra, environment="staging", ok=True):
    r = run("plan", "--changes", changes, *inputs(), "--account", "demo_account", "--environment", environment, *extra)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)
    return r


def plan_of(changes, *extra):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "changes.json"
        path.write_text(json.dumps(changes), encoding="utf-8")
        return plan(path, *extra)


def by_request(p):
    out = {}
    for c in p["changes"]:
        out.setdefault(c["request"], []).append(c)
    return out


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = plan()
        cls.r = by_request(cls.p)

    def test_shared_plan_shape(self):
        self.assertEqual((self.p["account"], self.p["environment"], self.p["site_group_id"]),
                         ("demo_account", "staging", None))
        self.assertEqual([c["n"] for c in self.p["changes"]], list(range(1, len(self.p["changes"]) + 1)))
        for c in self.p["changes"]:
            self.assertTrue(CHANGE_KEYS <= set(c), c["n"])
            self.assertIn(c["status"], ("ready", "blocked", "no_change"))
            self.assertIn(c["live_impact"], ("none", "live"))
            self.assertIsInstance(c["undo"], list)
            if c["status"] == "ready":
                self.assertEqual(c["payload"]["environment"], "staging")
                self.assertEqual(c["payload"]["account_name"], "demo_account")
                self.assertTrue(c["undo"], c["n"])

    def test_existing_global_rule_is_updated_not_duplicated_but_blocked_by_running_tests(self):
        c, = self.r[1]
        self.assertEqual((c["kind"], c["tool"], c["payload"]["rule_id"]), ("update", "update_facet_rule", 501))
        self.assertEqual(c["payload"]["excluded_facets"], ["countryOfOrigin", "cluster", "margin"])
        self.assertEqual(c["payload"]["always_included_facets"], ["category", "brand", "colors", "price"])
        self.assertEqual(c["status"], "blocked")
        self.assertTrue(any("global change" in p for p in c["problems"]))

    def test_category_update_replaces_lists_with_undo(self):
        c, = self.r[2]
        self.assertEqual(c["status"], "ready")
        self.assertEqual(c["payload"]["boosted_facets"], ["product_size", "colors", "price"])
        self.assertEqual(c["payload"]["always_included_facets"], ["colors"])
        self.assertNotIn("excluded_facets", c["payload"])
        undo = c["undo"][0]["payload"]
        self.assertEqual(undo["boosted_facets"], ["colors", "rating", "gender"])
        self.assertEqual(undo["always_included_facets"], ["gender", "rating", "colors"])
        self.assertEqual(c["live_impact"], "live")

    def test_new_rule_created_off_then_enabled_alone(self):
        create, enable = self.r[3]
        self.assertEqual((create["kind"], create["tool"]), ("create", "create_facet_rule"))
        self.assertIs(create["payload"]["enabled"], False)
        self.assertEqual(create["payload"]["queries"],
                         [{"query": "skirts", "queryType": "sitesearch", "matchType": "EXACT_MATCH"}])
        self.assertEqual(create["live_impact"], "none")
        self.assertEqual(create["undo"][0]["tool"], "delete_facet_rule")
        self.assertEqual(create["undo"][0]["payload"]["rule_id"], f"<id returned by change {create['n']}>")
        self.assertEqual((enable["kind"], enable["after_change"]), ("enable", create["n"]))
        self.assertEqual(enable["payload"]["rule_id"], f"<id returned by change {create['n']}>")
        self.assertIn([enable["n"]], self.p["batches"])

    def test_disabled_existing_rule_update_and_separate_switch_on(self):
        update, enable = self.r[4]
        self.assertEqual(update["payload"]["boosted_facets"], ["gender", "product_size"])
        self.assertEqual(update["live_impact"], "none")  # the rule is off
        self.assertNotIn("enabled", update["payload"])
        self.assertEqual((enable["kind"], enable["payload"]["enabled"]), ("enable", True))
        self.assertIn([enable["n"]], self.p["batches"])

    def test_running_experiment_blocks_rule_and_query(self):
        c, = self.r[5]
        self.assertEqual(c["status"], "blocked")
        self.assertTrue(any("Category test" in p and "category 30100" in p for p in c["problems"]))
        c, = self.r[7]
        self.assertEqual(c["status"], "blocked")
        self.assertTrue(any("Shorts ranking" in p for p in c["problems"]))
        self.assertFalse(any("Category test" in p for p in c["problems"]))
        # A completed test on rule 502 doesn't block it.
        self.assertEqual(self.r[2][0]["status"], "ready")

    def test_partial_overlap_is_blocked(self):
        c, = self.r[6]
        self.assertEqual(c["status"], "blocked")
        self.assertIn("505", c["problems"][0])

    def test_delete_alone_with_recreate_undo(self):
        c, = self.r[8]
        self.assertEqual((c["kind"], c["status"], c["live_impact"]), ("delete", "ready", "none"))
        self.assertEqual(self.p["batches"][-1], [c["n"]])
        rec = c["undo"][0]
        self.assertEqual(rec["tool"], "create_facet_rule")
        self.assertIs(rec["payload"]["enabled"], False)
        self.assertEqual(rec["payload"]["audience_id"], 77)
        self.assertEqual(rec["payload"]["boosted_facets"], ["brand"])
        self.assertEqual(rec["payload"]["facet_items"][0]["customizationType"], "value_configs_facets")
        self.assertEqual(len(c["undo"]), 1)  # it was off, so no switch-on step

    def test_batches_ordinary_first_then_each_switch_on_and_delete(self):
        kinds = {c["n"]: c["kind"] for c in self.p["changes"]}
        first = self.p["batches"][0]
        self.assertTrue(all(kinds[n] in ("create", "update", "disable") for n in first))
        for b in self.p["batches"][1:]:
            self.assertEqual(len(b), 1)
            self.assertIn(kinds[b[0]], ("enable", "delete"))

    def test_no_editor_emails_in_plan(self):
        self.assertNotIn("example.com", json.dumps(self.p))

    def test_site_group_in_every_payload_and_undo(self):
        p = plan(FX / "changes.json", "--site-group-id", "site-a")
        for c in p["changes"]:
            if c["status"] == "ready":
                self.assertEqual(c["payload"]["site_group_id"], "site-a")
                for u in c["undo"]:
                    self.assertEqual(u["payload"]["site_group_id"], "site-a")


class CheckTest(unittest.TestCase):
    def test_never_show_and_unknown_and_not_facetable(self):
        p = plan_of([{"action": "set", "scope": "category", "targets": ["60100"],
                      "add": {"boost": ["margin", "made_up"], "always_show": ["description"], "hide": ["internal_sku"]}}])
        c = p["changes"][0]
        self.assertEqual(c["status"], "blocked")
        text = " ".join(c["problems"])
        self.assertIn("'margin'", text)
        self.assertIn("'made_up'", text)
        self.assertIn("'description' isn't facetable", text)
        self.assertTrue(any("internal_sku" in w for w in c["warnings"]))  # hiding an unknown name only warns

    def test_hide_moves_facet_out_of_show_lists(self):
        p = plan_of([{"action": "update", "rule_id": 502, "add": {"hide": ["rating"]}}])
        c = p["changes"][0]
        self.assertEqual(c["status"], "ready")
        self.assertEqual(c["payload"]["boosted_facets"], ["colors", "gender"])
        self.assertEqual(c["payload"]["excluded_facets"], ["rating"])
        self.assertNotIn("rating", c["payload"]["always_included_facets"])

    def test_conflicting_replace_lists_blocked(self):
        p = plan_of([{"action": "update", "rule_id": 502, "facets": {"boost": ["colors"], "hide": ["colors"]}}])
        self.assertEqual(p["changes"][0]["status"], "blocked")

    def test_dashboard_only_change_blocked(self):
        p = plan_of([{"action": "update", "rule_id": 502, "merge": {"colors": ["grey", "gray"]}}])
        self.assertTrue(any("dashboard" in x for x in p["changes"][0]["problems"]))

    def test_no_change_and_already_disabled(self):
        p = plan_of([{"action": "update", "rule_id": 502, "add": {"boost": [{"facet": "colors", "position": 1}]}},
                     {"action": "disable", "rule_id": 503}])
        self.assertEqual([c["status"] for c in p["changes"]], ["no_change", "no_change"])
        self.assertEqual(p["batches"], [])

    def test_disable_and_two_changes_to_one_rule(self):
        p = plan_of([{"action": "disable", "rule_id": 502}, {"action": "delete", "rule_id": 502}])
        a, b = p["changes"]
        self.assertEqual((a["kind"], a["status"], a["payload"]["enabled"]), ("disable", "ready", False))
        self.assertEqual(a["undo"][0]["payload"]["enabled"], True)
        self.assertEqual(b["status"], "blocked")

    def test_rule_without_detail_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps([{"action": "set", "scope": "category", "targets": ["21200"],
                                         "add": {"hide": ["season"]}}]), encoding="utf-8")
            r = run("plan", "--changes", path, "--rules", FX / "rules_category.json", "--account", "demo_account",
                    "--environment", "staging")
        p = json.loads(r.stdout)
        self.assertEqual(p["changes"][0]["status"], "blocked")
        self.assertIn("get_facet_rule", p["changes"][0]["problems"][0])
        self.assertIn("warning", p)  # no experiments file

    def test_unknown_category_warns(self):
        p = plan_of([{"action": "set", "scope": "category", "targets": ["99999"], "add": {"hide": ["season"]}}])
        self.assertTrue(any("99999" in w for w in p["changes"][0]["warnings"]))

    def test_account_and_environment_required(self):
        r = run("plan", "--changes", FX / "changes.json", "--account", "demo_account")
        self.assertNotEqual(r.returncode, 0)
        r = run("plan", "--changes", FX / "changes.json", "--environment", "staging")
        self.assertNotEqual(r.returncode, 0)

    def test_denied_input_stops_without_repeating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("plan", "--changes", FX / "changes.json", "--rules", FX / "denied.json",
                    "--account", "demo_account", "--environment", "staging")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("ACCESS_DENIED", r.stdout)


class ExperimentTest(unittest.TestCase):
    def plan_with(self, experiments, changes):
        with tempfile.TemporaryDirectory() as tmp:
            e, c = Path(tmp) / "e.json", Path(tmp) / "c.json"
            e.write_text(json.dumps({"result": {"success": True, "data": experiments}}), encoding="utf-8")
            c.write_text(json.dumps(changes), encoding="utf-8")
            r = run("plan", "--changes", c, "--rules", FX / "rules_category.json", "--rule", f"502={FX / 'rule_502.json'}",
                    "--experiments", e, "--account", "demo_account", "--environment", "staging")
        self.assertEqual(r.returncode, 0, r.stdout)
        return json.loads(r.stdout)

    def exp(self, status, query_type="category", query="21200"):
        e = {"id": 7, "experimentName": "Some test",
             "buckets": [{"id": 1, "ruleIdentifierInfo": {"id": 8001, "query": [{"query": query, "queryType": query_type}]}}]}
        if status is not None:
            e["experimentStatus"] = status
        return e

    def test_unknown_or_missing_status_blocks_finished_does_not(self):
        change = [{"action": "update", "rule_id": 502, "add": {"hide": ["season"]}}]
        for status, blocked in (("PAUSED", True), (None, True), ("RUNNING", True), ("DRAFT", False),
                                ("Completed", False), ("ARCHIVED", False)):
            p = self.plan_with([self.exp(status)], change)
            self.assertEqual(p["changes"][0]["status"] == "blocked", blocked, status)

    def test_experiment_query_types_are_mapped(self):
        change = [{"action": "set", "scope": "search", "targets": ["Shorts"], "add": {"boost": ["colors"]}}]
        for qt in ("SITE_SEARCH", "search", "sitesearch"):
            p = self.plan_with([self.exp("RUNNING", qt, "shorts")], change)
            self.assertEqual(p["changes"][0]["status"], "blocked", qt)

    def test_global_change_blocked_by_any_unfinished_experiment(self):
        change = [{"action": "set", "scope": "global", "add": {"hide": ["cluster"]}}]
        p = self.plan_with([self.exp("PAUSED", "category", "99999")], change)
        self.assertEqual(p["changes"][0]["status"], "blocked")

    def test_experiments_required_for_ready_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "c.json"
            c.write_text(json.dumps([{"action": "disable", "rule_id": 502}]), encoding="utf-8")
            r = run("plan", "--changes", c, "--rule", f"502={FX / 'rule_502.json'}", "--account", "demo_account",
                    "--environment", "staging")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--experiments", r.stdout)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        r = run("plan", "--changes", FX / "changes.json", *inputs(), "--account", "demo_account",
                "--environment", "staging", "--out", self.dir / "plan.json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.plan = json.loads((self.dir / "plan.json").read_text(encoding="utf-8"))
        self.n = {(c["request"], c["kind"]): c["n"] for c in self.plan["changes"]}

    def tearDown(self):
        self.tmp.cleanup()

    def readback(self, name, rule_file, edit):
        data = json.loads((FX / rule_file).read_text(encoding="utf-8"))
        edit(data["data"]["data"])
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def verify(self, *pairs):
        args = [a for n, path in pairs for a in ("--readback", f"{n}={path}")]
        return run("verify", "--plan", self.dir / "plan.json", *args)

    def test_update_in_place_and_not_in_place(self):
        def done(rec):
            rec["customizationItems"]["boosted_facets"] = {"product_size": 1, "colors": 2, "price": 3}
            rec["customizationItems"]["always_included_facets"] = ["product_size", "colors", "price"]
        good = self.readback("good.json", "rule_502.json", done)
        r = self.verify((self.n[(2, "update")], good), (self.n[(8, "delete")], FX / "not_found.json"))
        out = json.loads(r.stdout)
        self.assertEqual([x["result"] for x in out["results"]], ["in_place", "gone"])
        self.assertTrue(out["all_match"])
        self.assertNotIn("search.example.test", r.stdout)
        r = self.verify((self.n[(2, "update")], FX / "rule_502.json"))
        res = json.loads(r.stdout)["results"][0]
        self.assertEqual(res["result"], "not_in_place")
        self.assertIn("boost", res["detail"])

    def test_create_readback_takes_new_id(self):
        def created(rec):
            rec.update(id=9210, enabled=False, name="Skirts facets",
                       queries=[{"query": "skirts", "queryType": "sitesearch", "matchType": "EXACT_MATCH"}],
                       customizationItems={"boosted_facets": {"product_size": 1, "colors": 2},
                                           "always_included_facets": ["product_size", "colors"]})
        path = self.readback("created.json", "rule_503.json", created)
        res = json.loads(self.verify((self.n[(3, "create")], path)).stdout)["results"][0]
        self.assertEqual((res["result"], res["rule_id"]), ("in_place", 9210))

    def test_delete_still_there_and_context_error_stops(self):
        r = self.verify((self.n[(8, "delete")], FX / "rule_506.json"))
        self.assertEqual(json.loads(r.stdout)["results"][0]["result"], "not_in_place")
        r = self.verify((self.n[(8, "delete")], FX / "denied.json"))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("ACCESS_DENIED", r.stdout)

    def test_bare_error_text_and_unknown_change(self):
        path = self.dir / "err.txt"
        path.write_text("Client error '404 Not Found' for url 'https://search.example.test/x/506'\n", encoding="utf-8")
        out = json.loads(self.verify((self.n[(8, "delete")], path)).stdout)
        self.assertEqual(out["results"][0]["result"], "gone")
        r = self.verify((999, path))
        self.assertNotEqual(r.returncode, 0)

    def test_not_found_that_isnt_about_the_rule_stops(self):
        for text in ("Tool 'get_facet_rule' not found", "Client error '404 Not Found' for url 'https://search.example.test/x/5060'"):
            path = self.dir / "err.json"
            path.write_text(json.dumps({"success": False, "error": text}), encoding="utf-8")
            r = self.verify((self.n[(8, "delete")], path))
            self.assertNotEqual(r.returncode, 0, text)
            out = json.loads(r.stdout)
            self.assertIs(out["ok"], False)
            self.assertNotIn("results", out)
            self.assertNotIn("search.example.test", r.stdout)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))

    def test_fixtures_end_with_newline(self):
        for f in FX.iterdir():
            self.assertTrue(f.read_bytes().endswith(b"\n"), f.name)


if __name__ == "__main__":
    unittest.main()
