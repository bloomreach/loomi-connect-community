"""Tests for discovery-redirect-fixer's redirect_plan.py: turning redirect fixes into a change plan with before,
after, payload and undo. All fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-redirect-fixer"
SCRIPT = SKILL / "scripts/redirect_plan.py"
FX = ROOT / "tests/fixtures/discovery/redirect_fixer"
DETAILS = ["detail_9001.json", "detail_9002.json", "detail_9003.json", "detail_9004.json"]


def run(*args):
    """Run the script by its full path from an empty folder, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def plan(changes="changes.json", *extra, details=True):
    args = ["--changes", changes if Path(str(changes)).is_absolute() else FX / changes,
            "--redirects", FX / "redirects_list.json"]
    if details:
        for d in DETAILS:
            args += ["--redirects", FX / d]
    args += ["--queries", FX / "queries_perf.json", "--experiments", FX / "experiments_running.json",
             "--account", "acme_demo", "--environment", "staging", "--today", "2026-11-03", *extra]
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def write_changes(tmp, changes):
    p = Path(tmp) / "changes.json"
    p.write_text(json.dumps(changes), encoding="utf-8")
    return p


def change(out, n):
    return next(c for c in out["changes"] if c["n"] == n)


def checks(c, severity=None):
    return [x["check"] for x in c["checks"] if severity in (None, x["severity"])]


class RedirectPlanTest(unittest.TestCase):
    def test_every_ready_change_has_before_after_payload_and_undo(self):
        out = plan()
        for c in out["changes"]:
            if c["status"] == "ready":
                for k in ("before", "after", "payload", "undo", "live_impact"):
                    self.assertIn(k, c, (c["n"], k))
                self.assertEqual(c["payload"]["arguments"]["environment"], "staging")
                self.assertEqual(c["undo"]["arguments"]["account_name"], "acme_demo")
        self.assertEqual(out["counts"], {"ready": 4, "blocked": 5, "no_change": 1})

    def test_update_changes_only_what_differs_and_undoes_it(self):
        c = change(plan(), 1)
        self.assertEqual(c["payload"]["arguments"], {"account_name": "acme_demo", "environment": "staging",
                                                     "rule_id": 9001, "destination_url": "https://www.example-shop.test/returns"})
        self.assertEqual(c["undo"]["arguments"]["destination_url"], "www.example-shop.test/returns")
        self.assertEqual(c["before"], {"destination_url": "www.example-shop.test/returns"})
        self.assertEqual(change(plan(), 2)["undo"]["arguments"]["redirect_type"], "redirect_phrases")

    def test_create_is_disabled_with_a_separate_enable_step(self):
        c = change(plan(), 3)
        self.assertIs(c["payload"]["arguments"]["enabled"], False)
        self.assertEqual(c["payload"]["tool"], "create_redirect")
        self.assertEqual(c["then_enable"]["arguments"]["enabled"], True)
        self.assertEqual(c["then_enable"]["undo"]["arguments"]["enabled"], False)
        self.assertEqual(c["undo"]["tool"], "delete_redirect")
        self.assertIn("Live for every shopper", c["then_enable"]["live_impact"])

    def test_create_left_disabled_has_no_enable_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_changes(tmp, [{"action": "create", "queries": ["store hours"], "redirect_type": "redirect_terms",
                                            "destination_url": "https://www.example-shop.test/stores", "enabled": False,
                                            "started_at": "2026-12-01", "ended_at": "2027-01-15T00:00:00Z"}]))
        c = out["changes"][0]
        self.assertNotIn("then_enable", c)
        self.assertEqual(c["after"]["started_at"], "2026-12-01T00:00Z")

    def test_deletes_are_confirmed_separately_with_a_recreate_undo(self):
        out = plan()
        c = change(out, 4)
        self.assertTrue(c["separate_yes"])
        self.assertEqual(out["confirm"], {"batch": [1, 2, 3], "deletes_each_separately": [4]})
        self.assertEqual(c["undo"]["tool"], "create_redirect")
        self.assertEqual(c["undo"]["arguments"]["audience_id"], 77)
        self.assertEqual(c["undo"]["arguments"]["started_at"], 1790000000000)
        self.assertIn("permanent", checks(c, "warning"))

    def test_running_tests_block_changes(self):
        out = plan()
        self.assertIn("a/b test", checks(change(out, 5), "blocker"))  # rule in an A/B test
        self.assertIn("a/b test", checks(change(out, 10), "blocker"))  # query in a running experiment
        self.assertIn("revenue", checks(change(out, 10), "warning"))

    def test_ended_experiments_dont_block(self):
        out = plan()
        self.assertEqual(change(out, 3)["status"], "ready")  # 'track order' is only in an ENDED experiment

    def test_keyword_conflicts_block(self):
        c = change(plan(), 6)
        self.assertIn("conflict", checks(c, "blocker"))

    def test_url_and_schedule_checks(self):
        c = change(plan(), 7)
        msgs = [x["message"] for x in c["checks"]]
        self.assertTrue(any("spaces" in m for m in msgs))
        self.assertTrue(any("placeholder host" in m for m in msgs))
        self.assertTrue(any("unfinished" in m for m in msgs))
        self.assertTrue(any("http, not https" in m for m in msgs))
        self.assertIn("schedule", checks(c, "blocker"))

    def test_needs_detail_and_detects_no_change(self):
        out = plan()
        self.assertIn("Fetch redirect 9005", change(out, 8)["checks"][0]["message"])
        self.assertEqual(change(out, 9)["status"], "no_change")

    def test_batch_cap_defers_the_rest(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        out = plan()
        self.assertEqual(len(out["changes"]), rules["max_changes_per_batch"])
        self.assertEqual([d["n"] for d in out["deferred"]], [11, 12])

    def test_phrase_match_revenue_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_changes(tmp, [
                {"action": "update", "rule_id": 9002, "queries": ["sale", "clearance"]},
                {"action": "create", "queries": ["jackets"], "redirect_type": "redirect_phrases",
                 "destination_url": "https://www.example-shop.test/jackets"},
                {"action": "frobnicate"},
                {"action": "update", "rule_id": "abc"},
                {"action": "delete", "rule_id": 4242}]))
        sale = out["changes"][0]
        self.assertIn("scope", checks(sale, "warning"))
        self.assertTrue(any("'sale dresses' is caught" in x["message"] for x in sale["checks"]))
        self.assertIn("revenue", checks(out["changes"][1], "warning"))
        self.assertEqual([c["status"] for c in out["changes"][2:]], ["blocked"] * 3)

    def test_schedule_undo_that_update_cant_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_changes(tmp, [{"action": "update", "rule_id": 9003, "ended_at": "2027-01-01"}]))
        c = out["changes"][0]
        self.assertNotIn("ended_at", c["undo"]["arguments"])
        self.assertIn("dashboard", c["undo"]["note"])

    def test_changes_object_form_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.json"
            out = plan("changes_dict.json", "--out", out_path)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), out)
        self.assertEqual(out["changes"][0]["after"], {"enabled": False})
        self.assertNotIn("editor@example.test", json.dumps(out))

    def test_errors_are_clean(self):
        base = ["--redirects", FX / "redirects_list.json", "--account", "a", "--environment", "staging"]
        for changes, extra, needle in [
            (FX / "changes_bad_date.json", [], "isn't an ISO date"),
            (FX / "changes_not_list.json", [], "expected a JSON list"),
            (FX / "missing.json", [], "can't read it"),
            (FX / "changes.json", ["--redirects", FX / "denied.json"], "ACCESS_DENIED"),
            (FX / "changes.json", ["--redirects", FX / "account_error.json"], "isn't repeated because it can list"),
        ]:
            r = run("--changes", changes, *base, *extra)
            self.assertEqual(r.returncode, 1, changes)
            self.assertIn(needle, json.loads(r.stdout)["error"])
        self.assertNotIn("gamma", run("--changes", FX / "changes.json", *base, "--redirects", FX / "account_error.json").stdout)
        r = run("--changes", FX / "changes.json", *base, "--today", "03/11/2026")
        self.assertEqual(r.returncode, 2)
        self.assertIn("YYYY-MM-DD", r.stderr)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
