"""Tests for engagement-ab-test-setup's ab_split_plan.py: planning an ab-split node in a scenario (message, holdout
and timing tests), blocking unsafe plans, re-checking before the write and verifying the read-back. All fixtures are
synthetic."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-ab-test-setup"
SCRIPT = SKILL / "scripts/ab_split_plan.py"
FX = ROOT / "tests/fixtures/engagement/engagement_ab_test_setup"
PROJECT = "00000000-0000-0000-0000-000000000000"


def run(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


def edges(payload):
    return {(c["source"]["node_id"], c["source"]["connector_index"], c["destination"]["node_id"])
            for c in payload["connections"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, obj):
        p = self.dir / name
        p.write_text(json.dumps(obj) + "\n", encoding="utf-8")
        return p

    def plan(self, spec="spec_message.json", scenario="scenario_draft.json", extra=()):
        spec_path = spec if isinstance(spec, Path) else FX / spec
        r = run("plan", "--scenario", FX / scenario, "--spec", spec_path, "--project-id", PROJECT,
                "--project-name-file", FX / "project.txt", "--out", self.dir / "plan.json", *extra, cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout), json.loads((self.dir / "plan.json").read_text(encoding="utf-8"))

    def readback_from(self, full, mutate=None, status="draft"):
        """A read-back that looks like the planned payload saved by Engagement."""
        payload = copy.deepcopy(full["changes"][0]["payload"]["payload"])
        payload.update({"_id": "aaaaaaaaaaaaaaaaaaaaaaaa", "status": status})
        if mutate:
            mutate(payload)
        return self.write("readback.json", {"result": {"success": True, "data": payload}})

    def verify(self, readback):
        return run("verify", "--plan", self.dir / "plan.json", "--readback", f"1={readback}", cwd=self.dir)


class PlanTest(Base):
    def test_message_test_splits_before_the_email_and_copies_it(self):
        out, full = self.plan()
        ch = full["changes"][0]
        self.assertEqual((ch["status"], ch["kind"], ch["tool"], ch["live_impact"]),
                         ("ready", "update", "update_scenario", "none"))
        self.assertEqual(full["batches"], [[1]])
        payload = ch["payload"]["payload"]
        split = next(n for n in payload["nodes"] if n["type"] == "ab-split")
        self.assertEqual(split["id"], 5)
        self.assertEqual([(v["id"], v["name"], v["percentage"]) for v in split["variants"]],
                         [(1, "Control", 50), (2, "Discount", 50)])
        self.assertEqual((split["highest_variant_id_used"], split["variants_immutable"], split["touched"]), (2, False, False))
        b = next(n for n in payload["nodes"] if n["id"] == 6)
        self.assertEqual(b["type"], "send-email-action")
        self.assertNotIn("version", b)
        self.assertIn("design", b)
        e = edges(payload)
        self.assertNotIn((1, 1, 2), e)
        self.assertTrue({(1, 1, 5), (5, 1, 2), (5, 2, 6), (6, 1, 3)} <= e)
        self.assertEqual(payload["last_node_id"], 6)
        for k in ("_id", "status", "edited", "trigger", "customer_filter", "created_by_display_name"):
            self.assertNotIn(k, payload)
        self.assertTrue(any("exact copy" in w for w in ch["warnings"]))
        self.assertEqual(out["changes"][0]["payload"], "(in the --out file)")
        self.assertEqual(full["project_name"], "Example Retail")

    def test_existing_nodes_keep_their_versions_and_undo_restores_the_stored_flow(self):
        _, full = self.plan()
        ch = full["changes"][0]
        email = next(n for n in ch["payload"]["payload"]["nodes"] if n["id"] == 2)
        self.assertEqual(email["version"], 3)
        undo = ch["undo"][0]
        self.assertEqual(undo["tool"], "update_scenario")
        self.assertEqual(len(undo["payload"]["payload"]["nodes"]), 5)
        self.assertIn((1, 1, 2), edges(undo["payload"]["payload"]))

    def test_variant_node_from_another_step_becomes_variant_b(self):
        _, full = self.plan(extra=("--variant-node", FX / "variant_node.json"))
        ch = full["changes"][0]
        b = next(n for n in ch["payload"]["payload"]["nodes"] if n["id"] == 6)
        self.assertEqual(b["design"]["data"]["subject"], "10% off your cart")
        self.assertNotIn("version", b)
        self.assertFalse(any("exact copy" in w for w in ch["warnings"]))
        self.assertTrue(any("another step" in w for w in ch["warnings"]))

    def test_holdout_branch_leads_nowhere(self):
        _, full = self.plan("spec_holdout.json")
        payload = full["changes"][0]["payload"]["payload"]
        e = edges(payload)
        self.assertTrue({(1, 1, 5), (5, 1, 2)} <= e)
        self.assertFalse(any(s == 5 and o == 2 for s, o, _ in e))
        self.assertEqual(payload["last_node_id"], 5)
        self.assertIsNone(full["changes"][0]["after"]["variant_node_id"])

    def test_timing_test_adds_a_second_wait_that_rejoins_the_flow(self):
        _, full = self.plan("spec_timing.json")
        payload = full["changes"][0]["payload"]["payload"]
        wait = next(n for n in payload["nodes"] if n["id"] == 6)
        self.assertEqual((wait["type"], wait["units"], wait["count"]), ("wait-action", "hours", 24))
        self.assertTrue({(0, 0, 5), (5, 1, 1), (5, 2, 6), (6, 1, 2)} <= edges(payload))

    def test_running_scenario_is_blocked_without_a_copy_name(self):
        _, full = self.plan(scenario="scenario_active.json")
        ch = full["changes"][0]
        self.assertEqual(ch["status"], "blocked")
        self.assertEqual(full["batches"], [])
        self.assertTrue(any("copy_name" in p for p in ch["problems"]))

    def test_running_scenario_with_copy_name_plans_a_new_draft(self):
        _, full = self.plan("spec_copy.json", scenario="scenario_active.json")
        ch = full["changes"][0]
        self.assertEqual((ch["status"], ch["kind"], ch["tool"]), ("ready", "create", "create_scenario"))
        self.assertNotIn("scenario_id", ch["payload"])
        payload = ch["payload"]["payload"]
        self.assertEqual(payload["name"], "Cart reminder flow - holdout test")
        self.assertTrue(all("version" not in n for n in payload["nodes"]))
        self.assertEqual(ch["undo"], [])
        self.assertIn("never deletes", ch["undo_note"])

    def test_missing_designs_block_the_plan(self):
        _, full = self.plan(scenario="scenario_no_designs.json")
        ch = full["changes"][0]
        self.assertEqual(ch["status"], "blocked")
        self.assertTrue(any("include_node_designs" in p for p in ch["problems"]))

    def test_bad_specs_are_blocked(self):
        base = json.loads((FX / "spec_message.json").read_text(encoding="utf-8"))
        cases = {
            "no edge": {"edge": {"from_node": 3, "from_output": 1, "to_node": 2}},
            "shares": {"variant": {"name": "Discount", "percentage": 40}},
            "tiny share": {"control": {"name": "Control", "percentage": 98}, "variant": {"name": "B", "percentage": 2}},
            "same names": {"variant": {"name": "control", "percentage": 50}},
            "wrong node": {"edge": {"from_node": 0, "from_output": 0, "to_node": 1}},
            "test type": {"test": "subject"},
        }
        for label, change in cases.items():
            with self.subTest(label):
                spec = dict(base, **change)
                _, full = self.plan(self.write(f"spec_{len(label)}.json", spec))
                self.assertEqual(full["changes"][0]["status"], "blocked", label)

    def test_timing_without_a_different_wait_is_blocked(self):
        spec = json.loads((FX / "spec_timing.json").read_text(encoding="utf-8"))
        spec["timing"] = {"units": "hours", "count": 4}
        _, full = self.plan(self.write("t.json", spec))
        self.assertEqual(full["changes"][0]["status"], "blocked")

    def test_existing_split_is_a_warning_and_ids_follow_it(self):
        _, full = self.plan(scenario="scenario_with_split.json")
        ch = full["changes"][0]
        self.assertEqual(ch["status"], "ready")
        self.assertTrue(any("already has a split" in w for w in ch["warnings"]))
        self.assertEqual(ch["after"]["split_node_id"], 10)

    def test_big_holdout_is_a_warning(self):
        spec = json.loads((FX / "spec_holdout.json").read_text(encoding="utf-8"))
        spec["control"]["percentage"], spec["variant"]["percentage"] = 30, 70
        _, full = self.plan(self.write("h.json", spec))
        self.assertTrue(any("holdout gets" in w for w in full["changes"][0]["warnings"]))

    def test_plan_writes_only_its_out_file(self):
        self.plan()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["plan.json"])


class RecheckAndVerifyTest(Base):
    def test_recheck_unchanged_and_changed(self):
        self.plan()
        r = run("recheck", "--plan", self.dir / "plan.json", "--scenario", FX / "scenario_draft.json", cwd=self.dir)
        self.assertTrue(json.loads(r.stdout)["unchanged"])
        data = json.loads((FX / "scenario_draft.json").read_text(encoding="utf-8"))
        data["result"]["data"]["edited"] = 1700009999.0
        r = run("recheck", "--plan", self.dir / "plan.json", "--scenario", self.write("fresh.json", data), cwd=self.dir)
        out = json.loads(r.stdout)
        self.assertFalse(out["unchanged"])
        self.assertEqual(out["changed"], ["edited"])

    def test_verify_in_place(self):
        _, full = self.plan()
        out = json.loads(self.verify(self.readback_from(full)).stdout)
        res = out["results"][0]
        self.assertEqual(res["result"], "in_place", res)
        self.assertEqual(res["scenario_id"], "aaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertNotIn("alert", res)

    def test_verify_not_in_place_when_split_or_edges_differ(self):
        _, full = self.plan()

        def drop_split(p):
            p["nodes"] = [n for n in p["nodes"] if n["type"] != "ab-split"]

        def old_edge(p):
            p["connections"].append({"source": {"node_id": 1, "connector_index": 1},
                                     "destination": {"node_id": 2, "connector_index": 0}})

        def shares(p):
            split = next(n for n in p["nodes"] if n["type"] == "ab-split")
            split["variants"][0]["percentage"] = 60

        for mutate in (drop_split, old_edge, shares):
            with self.subTest(mutate.__name__):
                res = json.loads(self.verify(self.readback_from(full, mutate)).stdout)["results"][0]
                self.assertEqual(res["result"], "not_in_place")
                self.assertTrue(res["differences"])

    def test_verify_timing_wait(self):
        _, full = self.plan("spec_timing.json")

        def wrong_wait(p):
            next(n for n in p["nodes"] if n["id"] == 6)["count"] = 4

        self.assertEqual(json.loads(self.verify(self.readback_from(full)).stdout)["results"][0]["result"], "in_place")
        res = json.loads(self.verify(self.readback_from(full, wrong_wait)).stdout)["results"][0]
        self.assertEqual(res["result"], "not_in_place")

    def test_verify_holdout_branch_must_stay_empty(self):
        _, full = self.plan("spec_holdout.json")

        def lead(p):
            p["connections"].append({"source": {"node_id": 5, "connector_index": 2},
                                     "destination": {"node_id": 3, "connector_index": 0}})

        res = json.loads(self.verify(self.readback_from(full, lead)).stdout)["results"][0]
        self.assertEqual(res["result"], "not_in_place")

    def test_verify_alerts_when_the_flow_is_running(self):
        _, full = self.plan()
        res = json.loads(self.verify(self.readback_from(full, status="active")).stdout)["results"][0]
        self.assertIn("alert", res)

    def test_verify_not_found_and_context_errors(self):
        self.plan()
        res = json.loads(self.verify(FX / "readback_not_found.json").stdout)["results"][0]
        self.assertEqual(res["result"], "not_in_place")
        r = self.verify(FX / "readback_denied.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project", json.loads(r.stdout)["error"])

    def test_bad_inputs_fail_cleanly(self):
        r = run("plan", "--scenario", self.dir / "missing.json", "--spec", FX / "spec_message.json",
                "--project-id", PROJECT, "--project-name-file", FX / "project.txt", "--out", self.dir / "p.json",
                cwd=self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])
        self.plan()
        r = run("plan", "--scenario", FX / "scenario_draft.json", "--spec", FX / "spec_message.json",
                "--project-id", PROJECT, "--project-name-file", FX / "project.txt",
                "--out", self.dir / "no" / "dir" / "p.json", cwd=self.dir)
        self.assertEqual(r.returncode, 1)


class ContentLossTest(Base):
    def scenario_with(self, node, drop_edited=False):
        data = json.loads((FX / "scenario_draft.json").read_text(encoding="utf-8"))
        rec = data["result"]["data"]
        if node:
            rec["nodes"].append(node)
        if drop_edited:
            rec.pop("edited", None)
        return self.write(f"scenario_{len(list(self.dir.iterdir()))}.json", data)

    def test_any_design_carrying_step_without_a_design_blocks_the_plan(self):
        for node in ({"id": 7, "type": "serve-banner-action", "name": "Banner"},
                     {"id": 7, "type": "some-in-app-action", "name": "In-app"}):
            with self.subTest(node["type"]):
                r = run("plan", "--scenario", self.scenario_with(node), "--spec", FX / "spec_message.json",
                        "--project-id", PROJECT, "--project-name-file", FX / "project.txt",
                        "--out", self.dir / "plan.json", cwd=self.dir)
                ch = json.loads(r.stdout)["changes"][0]
                self.assertEqual(ch["status"], "blocked")
                self.assertTrue(any("Steps 7 have no design" in p for p in ch["problems"]), ch["problems"])

    def test_no_design_types_pass_without_a_design(self):
        node = {"id": 7, "type": "per-customer-webhook-action", "name": "Hook", "method": "POST"}
        r = run("plan", "--scenario", self.scenario_with(node), "--spec", FX / "spec_message.json",
                "--project-id", PROJECT, "--project-name-file", FX / "project.txt",
                "--out", self.dir / "plan.json", cwd=self.dir)
        ch = json.loads(r.stdout)["changes"][0]
        self.assertEqual(ch["status"], "ready", ch["problems"])
        self.assertEqual(ch["after"]["design_node_ids"], [2, 4, 9])  # split 8, variant B 9 follow node 7

    def test_verify_reports_steps_that_lost_their_design(self):
        _, full = self.plan()

        def strip(p):
            next(n for n in p["nodes"] if n["id"] == 4).pop("design")

        res = json.loads(self.verify(self.readback_from(full, strip)).stdout)["results"][0]
        self.assertEqual(res["result"], "not_in_place")
        self.assertIn("steps 4 had a design", res["reason"])
        self.assertIn("Don't send the plan's stored undo", res["next"])

    def test_restore_builds_a_fresh_plan_from_the_current_read(self):
        _, full = self.plan()
        now = self.readback_from(full)  # the split went in, but the user wants it out again
        r = run("restore", "--plan", self.dir / "plan.json", "--scenario", now, "--out", self.dir / "restore.json",
                cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        printed = json.loads(r.stdout)["changes"][0]
        self.assertEqual(printed["payload"], "(in the --out file)")
        ch = json.loads((self.dir / "restore.json").read_text(encoding="utf-8"))["changes"][0]
        self.assertEqual((ch["status"], ch["tool"]), ("ready", "update_scenario"))
        payload = ch["payload"]["payload"]
        self.assertEqual(sorted(n["id"] for n in payload["nodes"]), [0, 1, 2, 3, 4])
        self.assertIn((1, 1, 2), edges(payload))
        self.assertTrue(any("Remove the A/B split step 5" in w for w in ch["description"]))
        r = run("recheck", "--plan", self.dir / "restore.json", "--scenario", now, cwd=self.dir)
        self.assertTrue(json.loads(r.stdout)["unchanged"])
        restored = self.write("restored.json", {"result": {"success": True, "data": dict(
            payload, _id="aaaaaaaaaaaaaaaaaaaaaaaa", status="draft")}})
        r = run("verify", "--plan", self.dir / "restore.json", "--readback", f"1={restored}", cwd=self.dir)
        self.assertEqual(json.loads(r.stdout)["results"][0]["result"], "in_place")

    def test_restore_is_blocked_when_the_read_lacks_designs(self):
        _, full = self.plan()
        now = self.readback_from(full, lambda p: next(n for n in p["nodes"] if n["id"] == 2).pop("design"))
        r = run("restore", "--plan", self.dir / "plan.json", "--scenario", now, "--out", self.dir / "restore.json",
                cwd=self.dir)
        ch = json.loads(r.stdout)["changes"][0]
        self.assertEqual(ch["status"], "blocked")


class RecheckHashTest(Base):
    def test_an_edit_counts_as_a_change_when_edited_is_missing_from_both_fetches(self):
        data = json.loads((FX / "scenario_draft.json").read_text(encoding="utf-8"))
        data["result"]["data"].pop("edited")
        first = self.write("first.json", data)
        self.plan(scenario=first)
        r = run("recheck", "--plan", self.dir / "plan.json", "--scenario", first, cwd=self.dir)
        self.assertTrue(json.loads(r.stdout)["unchanged"])
        data["result"]["data"]["nodes"][1]["count"] = 8
        r = run("recheck", "--plan", self.dir / "plan.json", "--scenario", self.write("second.json", data),
                cwd=self.dir)
        out = json.loads(r.stdout)
        self.assertFalse(out["unchanged"])
        self.assertEqual(out["changed"], ["content_hash"])

    def test_a_plan_without_a_hash_counts_as_changed(self):
        self.plan()
        plan = json.loads((self.dir / "plan.json").read_text(encoding="utf-8"))
        plan["changes"][0]["before"].pop("content_hash")
        old = self.write("old_plan.json", plan)
        r = run("recheck", "--plan", old, "--scenario", FX / "scenario_draft.json", cwd=self.dir)
        self.assertFalse(json.loads(r.stdout)["unchanged"])


class WholeSharesTest(Base):
    def test_whole_percentages_are_written_as_integers(self):
        spec = json.loads((FX / "spec_message.json").read_text(encoding="utf-8"))
        spec["control"]["percentage"], spec["variant"]["percentage"] = 80.0, 20.0
        _, full = self.plan(self.write("s.json", spec))
        raw = (self.dir / "plan.json").read_text(encoding="utf-8")
        split = next(n for n in full["changes"][0]["payload"]["payload"]["nodes"] if n["type"] == "ab-split")
        self.assertEqual([v["percentage"] for v in split["variants"]], [80, 20])
        self.assertTrue(all(type(v["percentage"]) is int for v in split["variants"]))
        self.assertNotIn("80.0", raw)

    def test_fractional_percentages_stay_as_they_are(self):
        spec = json.loads((FX / "spec_message.json").read_text(encoding="utf-8"))
        spec["control"]["percentage"], spec["variant"]["percentage"] = 87.5, 12.5
        _, full = self.plan(self.write("s.json", spec))
        split = next(n for n in full["changes"][0]["payload"]["payload"]["nodes"] if n["type"] == "ab-split")
        self.assertEqual([v["percentage"] for v in split["variants"]], [87.5, 12.5])


class VariantProjectTest(Base):
    def test_variant_node_from_another_project_is_blocked(self):
        node = json.loads((FX / "variant_node.json").read_text(encoding="utf-8"))
        rec = node.get("result", node)
        rec = rec.get("data", rec) if isinstance(rec, dict) else rec
        rec = rec.get("node", rec) if isinstance(rec.get("node"), dict) else rec
        rec["project_id"] = "11111111-1111-1111-1111-111111111111"
        _, full = self.plan(extra=("--variant-node", self.write("vn.json", node)))
        ch = full["changes"][0]
        self.assertEqual(ch["status"], "blocked")
        self.assertTrue(any("another project" in p for p in ch["problems"]))


class RulesTest(unittest.TestCase):
    def test_every_rules_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertTrue(rules.get("about"))
        self.assertEqual(set(rules) - {"about", "notes"} - set(rules["notes"]), set())


if __name__ == "__main__":
    unittest.main()
