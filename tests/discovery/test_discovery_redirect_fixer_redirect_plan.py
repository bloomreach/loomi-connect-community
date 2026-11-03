"""Tests for discovery-redirect-fixer's redirect_plan.py: turning redirect fixes into a plan file (the shape in
docs/skill-authoring.md) with before, after, payload and undo, and checking writes with verify. All fixtures are
synthetic."""
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
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")


def run(*args):
    """Run the script by its full path from an empty folder, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def plan(changes="changes.json", *extra, details=True, experiments="experiments_running.json"):
    args = ["plan", "--changes", changes if Path(str(changes)).is_absolute() else FX / changes,
            "--redirects", FX / "redirects_list.json"]
    if details:
        for d in DETAILS:
            args += ["--redirects", FX / d]
    args += ["--queries", FX / "queries_perf.json", "--experiments", FX / experiments,
             "--account", "acme_demo", "--environment", "staging", "--today", "2026-11-03", *extra]
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def write_json(tmp, name, data):
    p = Path(tmp) / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def req(out, request, kind=None):
    """The planned change(s) for request number `request` (1-based position in the changes file)."""
    found = [c for c in out["changes"] if c["request"] == request and kind in (None, c["kind"])]
    assert found, (request, kind)
    return found[0]


def checks(items):
    return [x["check"] for x in items]


class PlanShapeTest(unittest.TestCase):
    def test_plan_file_shape(self):
        out = plan()
        for k in ("ok", "account", "environment", "site_group_id", "changes", "batches"):
            self.assertIn(k, out)
        self.assertEqual([c["n"] for c in out["changes"]], list(range(1, len(out["changes"]) + 1)))
        for c in out["changes"]:
            for k in CHANGE_KEYS:
                self.assertIn(k, c, (c["n"], k))
            self.assertIn(c["status"], ("ready", "blocked", "no_change"))
            self.assertIn(c["live_impact"], ("none", "live"))
            self.assertIsInstance(c["undo"], list)
            if c["status"] == "ready":
                self.assertEqual(c["payload"]["environment"], "staging")
                self.assertEqual(c["payload"]["account_name"], "acme_demo")
                for u in c["undo"]:
                    self.assertEqual(set(u) - {"note"}, {"tool", "payload"})
        self.assertEqual(out["counts"], {"ready": 6, "blocked": 6, "no_change": 1})

    def test_only_ready_changes_are_batched_and_switch_ons_and_deletes_go_alone(self):
        out = plan()
        ready = {c["n"] for c in out["changes"] if c["status"] == "ready"}
        batched = [n for b in out["batches"] for n in b]
        self.assertEqual(set(batched), ready)
        enable = req(out, 3, "enable")["n"]
        delete = req(out, 4, "delete")["n"]
        self.assertIn([enable], out["batches"])
        self.assertIn([delete], out["batches"])
        self.assertEqual(out["batches"][-1], [delete])  # deletes come last

    def test_site_group_is_in_every_payload_and_undo(self):
        out = plan("changes.json", "--site-group-id", "uk")
        for c in out["changes"]:
            if c["payload"]:
                self.assertEqual(c["payload"]["site_group_id"], "uk")
            for u in c["undo"]:
                self.assertEqual(u["payload"]["site_group_id"], "uk")

    def test_account_and_environment_are_required(self):
        for missing in ("--account", "--environment"):
            args = ["plan", "--changes", FX / "changes.json", "--redirects", FX / "redirects_list.json",
                    "--account", "a", "--environment", "staging"]
            i = args.index(missing)
            del args[i:i + 2]
            r = run(*args)
            self.assertEqual(r.returncode, 2, missing)


class PlanChangesTest(unittest.TestCase):
    def test_update_changes_only_what_differs_and_undoes_it(self):
        out = plan()
        c = req(out, 1)
        self.assertEqual(c["payload"], {"account_name": "acme_demo", "environment": "staging", "rule_id": 9001,
                                        "destination_url": "https://www.example-shop.test/returns"})
        self.assertEqual(c["undo"][0]["payload"]["destination_url"], "www.example-shop.test/returns")
        self.assertEqual(c["before"], {"destination_url": "www.example-shop.test/returns"})
        self.assertEqual(req(out, 2)["undo"][0]["payload"]["redirect_type"], "redirect_phrases")

    def test_create_is_switched_off_with_a_separate_enable_change(self):
        out = plan()
        create, enable = req(out, 3, "create"), req(out, 3, "enable")
        self.assertIs(create["payload"]["enabled"], False)
        self.assertEqual(create["live_impact"], "none")
        self.assertEqual(create["undo"][0]["tool"], "delete_redirect")
        self.assertEqual(enable["after_change"], create["n"])
        self.assertEqual(enable["payload"]["rule_id"], f"<id returned by change {create['n']}>")
        self.assertIs(enable["payload"]["enabled"], True)
        self.assertEqual(enable["live_impact"], "live")
        self.assertIs(enable["undo"][0]["payload"]["enabled"], False)

    def test_create_left_switched_off_has_no_enable_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_json(tmp, "c.json", [{"action": "create", "queries": ["store hours"],
                                                   "redirect_type": "redirect_terms",
                                                   "destination_url": "https://www.example-shop.test/stores",
                                                   "enabled": False, "started_at": "2026-12-01",
                                                   "ended_at": "2027-01-15T00:00:00Z"}]))
        self.assertEqual([c["kind"] for c in out["changes"]], ["create"])
        self.assertEqual(out["changes"][0]["after"]["started_at"], "2026-12-01T00:00Z")

    def test_blocked_create_has_no_enable_change(self):
        out = plan()
        self.assertEqual([c["kind"] for c in out["changes"] if c["request"] == 6], ["create"])

    def test_delete_undo_recreates_switched_off_then_enables_separately(self):
        c = req(plan(), 4, "delete")
        create, enable = c["undo"]
        self.assertEqual(create["tool"], "create_redirect")
        self.assertIs(create["payload"]["enabled"], False)
        self.assertEqual(create["payload"]["audience_id"], 77)
        self.assertEqual(create["payload"]["started_at"], 1790000000000)
        self.assertEqual((enable["tool"], enable["payload"]["enabled"]), ("update_redirect", True))
        self.assertIn("separately", enable["note"])
        self.assertIn("permanent", checks(c["warnings"]))

    def test_switching_on_an_existing_redirect_is_its_own_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_json(tmp, "c.json", [
                {"action": "update", "rule_id": 9001, "destination_url": "https://www.example-shop.test/returns"},
                {"action": "update", "rule_id": 9002, "enabled": False},
                {"action": "update", "rule_id": 9003, "enabled": False},
            ]))
            self.assertEqual(out["batches"], [[1, 2, 3]])
            # 9002 starts on; switching it off and then back on later is a switch-on of its own
            redirects = json.loads((FX / "detail_9002.json").read_text(encoding="utf-8"))
            redirects["result"]["data"]["data"]["enabled"] = False
            off = write_json(tmp, "off.json", redirects)
            r = run("plan", "--changes", write_json(tmp, "c2.json", [
                        {"action": "update", "rule_id": 9001, "name": "Returns page"},
                        {"action": "update", "rule_id": 9002, "enabled": True},
                        {"action": "update", "rule_id": 9002, "enabled": True, "name": "Sale page"}]),
                    "--redirects", FX / "redirects_list.json", "--redirects", FX / "detail_9001.json",
                    "--redirects", off, "--account", "a", "--environment", "staging", "--today", "2026-11-03")
        out = json.loads(r.stdout)
        self.assertEqual(req(out, 2)["kind"], "enable")
        self.assertTrue(req(out, 3)["switches_on"])
        self.assertEqual(req(out, 3)["kind"], "update")
        self.assertEqual(out["batches"], [[1], [2], [3]])

    def test_running_tests_block_changes(self):
        out = plan()
        self.assertIn("a/b test", checks(req(out, 5)["problems"]))  # rule in an A/B test
        self.assertIn("a/b test", checks(req(out, 10)["problems"]))  # query in a running experiment
        self.assertIn("revenue", checks(req(out, 10)["warnings"]))

    def test_ended_experiments_dont_block_and_statuses_are_case_insensitive(self):
        self.assertEqual(req(plan(), 3)["status"], "ready")  # 'track order' is only in an ENDED experiment
        with tempfile.TemporaryDirectory() as tmp:
            exps = write_json(tmp, "e.json", {"result": {"success": True, "data": [
                {"id": 1, "name": "Live test", "status": "Live", "buckets": [{"rules": [{"query": "track order"}]}]}]}})
            out = plan("changes.json", experiments=exps)
        self.assertEqual(req(out, 3)["status"], "blocked")

    def test_an_experiment_with_no_status_counts_as_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            exps = write_json(tmp, "e.json", {"result": {"success": True, "data": [
                {"id": 1, "name": "Unknown", "buckets": [{"rules": [{"query": "track order"}]}]}]}})
            out = plan("changes.json", experiments=exps)
        self.assertEqual(req(out, 3)["status"], "blocked")

    def test_keyword_conflicts_block(self):
        self.assertIn("conflict", checks(req(plan(), 6)["problems"]))

    def test_url_and_schedule_checks(self):
        c = req(plan(), 7)
        msgs = [x["message"] for x in c["problems"] + c["warnings"]]
        self.assertTrue(any("spaces" in m for m in msgs))
        self.assertTrue(any("placeholder host" in m for m in msgs))
        self.assertTrue(any("unfinished" in m for m in msgs))
        self.assertTrue(any("http, not https" in m for m in msgs))
        self.assertIn("schedule", checks(c["problems"]))

    def test_needs_detail_and_detects_no_change(self):
        out = plan()
        self.assertIn("Fetch redirect 9005", req(out, 8)["problems"][0]["message"])
        self.assertEqual(req(out, 9)["status"], "no_change")

    def test_today_and_the_default_use_the_same_midnight(self):
        with tempfile.TemporaryDirectory() as tmp:
            # An end time later today is not "already passed" when judged against midnight
            c = write_json(tmp, "c.json", [{"action": "update", "rule_id": 9001, "ended_at": "2026-11-03T18:00:00Z"}])
            out = plan(c)
        self.assertEqual(out["today"], "2026-11-03")
        self.assertEqual(req(out, 1)["status"], "ready")

    def test_batch_cap_counts_only_ready_changes(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        cap = rules["max_changes_per_batch"]
        creates = [{"action": "create", "queries": [f"help topic {i}"], "redirect_type": "redirect_terms",
                    "destination_url": f"https://www.example-shop.test/help/{i}", "enabled": False}
                   for i in range(cap + 2)]
        blocked = [{"action": "frobnicate"}] * 3
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_json(tmp, "c.json", blocked + creates))
        self.assertEqual(out["counts"]["ready"], cap)
        self.assertEqual(out["counts"]["blocked"], 3)
        self.assertEqual([d["request"] for d in out["deferred"]], [3 + cap + 1, 3 + cap + 2])

    def test_phrase_match_revenue_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_json(tmp, "c.json", [
                {"action": "update", "rule_id": 9002, "queries": ["sale", "clearance"]},
                {"action": "create", "queries": ["jackets"], "redirect_type": "redirect_phrases",
                 "destination_url": "https://www.example-shop.test/jackets"},
                {"action": "frobnicate"},
                {"action": "update", "rule_id": "abc"},
                {"action": "delete", "rule_id": 4242}]))
        sale = req(out, 1)
        self.assertIn("scope", checks(sale["warnings"]))
        self.assertTrue(any("'sale dresses' is caught" in x["message"] for x in sale["warnings"]))
        self.assertIn("revenue", checks(req(out, 2, "create")["warnings"]))
        self.assertEqual([req(out, r)["status"] for r in (3, 4, 5)], ["blocked"] * 3)
        self.assertIsNone(req(out, 3)["kind"])

    def test_schedule_undo_that_update_cant_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = plan(write_json(tmp, "c.json", [{"action": "update", "rule_id": 9003, "ended_at": "2027-01-01"}]))
        c = out["changes"][0]
        self.assertEqual(c["undo"], [])
        self.assertIn("dashboard", c["undo_note"])

    def test_changes_object_form_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.json"
            out = plan("changes_dict.json", "--out", out_path)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), out)
        self.assertEqual(out["changes"][0]["after"], {"enabled": False})
        self.assertEqual(out["changes"][0]["kind"], "disable")
        self.assertNotIn("editor@example.test", json.dumps(out))

    def test_output_is_the_same_on_every_run(self):
        self.assertEqual(plan(), plan())


class VerifyTest(unittest.TestCase):
    def verify(self, *readbacks, plan_file=None):
        with tempfile.TemporaryDirectory() as tmp:
            p = plan_file or write_json(tmp, "plan.json", plan())
            args = ["verify", "--plan", p]
            for rb in readbacks:
                args += ["--readback", rb]
            return run(*args)

    def test_in_place_not_in_place_and_gone(self):
        out = plan()
        create = req(out, 3, "create")["n"]
        delete = req(out, 4, "delete")["n"]
        r = self.verify(f"1={FX / 'detail_9001.json'}", f"{create}={FX / 'readback_new.json'}",
                        f"{delete}={FX / 'denied.json'}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = {x["n"]: x for x in json.loads(r.stdout)["results"]}
        self.assertEqual(res[1]["state"], "not_in_place")  # the read-back still has the old URL
        self.assertEqual(res[1]["mismatches"][0]["field"], "destination_url")
        self.assertEqual((res[create]["state"], res[create]["rule_id"]), ("in_place", 9104))
        self.assertEqual(res[delete]["state"], "gone")  # a not-found / success:false read-back

    def test_a_delete_still_present_is_not_gone(self):
        delete = req(plan(), 4, "delete")["n"]
        r = self.verify(f"{delete}={FX / 'detail_9003.json'}")
        self.assertEqual(json.loads(r.stdout)["results"][0]["state"], "not_in_place")

    def test_an_account_error_stops_verify_and_is_never_gone(self):
        delete = req(plan(), 4, "delete")["n"]
        r = self.verify(f"{delete}={FX / 'account_error.json'}")
        self.assertEqual(r.returncode, 1)
        err = json.loads(r.stdout)["error"]
        self.assertIn("isn't repeated because it can list", err)
        self.assertNotIn("gone", r.stdout)
        self.assertNotIn("gamma", r.stdout)

    def test_changes_without_a_read_back_are_listed_not_assumed(self):
        out = plan()
        delete = req(out, 4, "delete")["n"]
        r = self.verify(f"1={FX / 'detail_9001.json'}")
        self.assertIn(delete, json.loads(r.stdout)["not_checked"])

    def test_verify_errors_are_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_plan = write_json(tmp, "bad.json", {"changes": "nope"})
            r = self.verify(f"1={FX / 'detail_9001.json'}", plan_file=bad_plan)
            self.assertEqual(r.returncode, 1)
            self.assertIn("not a plan file", json.loads(r.stdout)["error"])
            r = self.verify(f"99={FX / 'detail_9001.json'}")
            self.assertEqual(r.returncode, 1)
            self.assertIn("no ready change 99", json.loads(r.stdout)["error"])
            r = self.verify("nonsense")
            self.assertEqual(r.returncode, 2)
            self.assertIn("N=FILE", r.stderr)
            r = self.verify(f"1={tmp}/a=b.json")  # split on the first "=" only
            self.assertEqual(r.returncode, 1)
            self.assertIn("a=b.json", json.loads(r.stdout)["error"])


class ErrorsTest(unittest.TestCase):
    def test_errors_are_clean(self):
        base = ["--redirects", FX / "redirects_list.json", "--account", "a", "--environment", "staging"]
        for changes, extra, needle in [
            (FX / "changes_bad_date.json", [], "isn't an ISO date"),
            (FX / "changes_not_list.json", [], "expected a JSON list"),
            (FX / "missing.json", [], "can't read it"),
            (FX / "changes.json", ["--redirects", FX / "denied.json"], "ACCESS_DENIED"),
            (FX / "changes.json", ["--redirects", FX / "account_error.json"], "isn't repeated because it can list"),
        ]:
            r = run("plan", "--changes", changes, *base, *extra)
            self.assertEqual(r.returncode, 1, changes)
            self.assertIn(needle, json.loads(r.stdout)["error"])
        r = run("plan", "--changes", FX / "changes.json", *base, "--redirects", FX / "account_error.json")
        self.assertNotIn("gamma", r.stdout)
        r = run("plan", "--changes", FX / "changes.json", *base, "--today", "03/11/2026")
        self.assertEqual(r.returncode, 2)
        self.assertIn("YYYY-MM-DD", r.stderr)

    def test_any_account_error_is_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            short = write_json(tmp, "e.json", {"result": {"success": False,
                                                          "error": "Unknown account. Try: alpha or beta"}})
            r = run("plan", "--changes", FX / "changes.json", "--redirects", short, "--account", "a",
                    "--environment", "staging")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("alpha", r.stdout)
        self.assertIn("isn't repeated", r.stdout)

    def test_unwritable_out_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("plan", "--changes", FX / "changes.json", "--redirects", FX / "redirects_list.json",
                    "--account", "a", "--environment", "staging", "--out", Path(tmp) / "no-such-dir" / "plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't write it", json.loads(r.stdout)["error"])


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
