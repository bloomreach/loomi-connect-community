"""Tests for scenario-template-launcher's scenario_clone_plan.py: the clone plan (the shape in docs/skill-authoring.md,
with project_id in place of account and environment), its on_conflict choices, the fix list of references that won't
resolve in the target, webhook secrecy, find before a second clone, and verify on the read-back. All fixtures are
synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/scenario-template-launcher"
SCRIPT = SKILL / "scripts/scenario_clone_plan.py"
FX = ROOT / "tests/fixtures/engagement/scenario-template-launcher"
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")
TARGET_LOOKUPS = ("--target-events", FX / "target_events.json", "--target-properties", FX / "target_properties.json",
                  "--target-consent", FX / "target_consent.json",
                  "--target-frequency-policies", FX / "target_policies.json",
                  "--target-integrations", FX / "target_integrations.json",
                  "--target-catalogs", FX / "target_catalogs.json", "--target-variables", FX / "target_variables.json",
                  "--source-recommendations", FX / "source_recommendation.json",
                  "--source-catalogs", FX / "source_catalogs.json")


def run(*args, cwd=None):
    """Run the script by its full path from an empty folder, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=cwd or tmp)
        if cwd is None:
            assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def plan(preview="preview_cross.json", target="tgt-proj", target_name="Target demo", extra=(), lookups=TARGET_LOOKUPS,
         ok=True, orgs=("Example Org", "Example Org"), source="source.json"):
    r = run("plan", "--source", FX / source, "--preview", FX / preview, "--source-project-id", "src-proj",
            "--source-project-name", "Source demo", "--project-id", target, "--project-name", target_name,
            "--source-org", orgs[0], "--target-org", orgs[1],
            "--target-scenarios", FX / "target_scenarios.json", "--today", "2026-11-05", *lookups, *extra)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)
    return r


def checks(entries):
    return [e["check"] for e in entries]


class PlanShape(unittest.TestCase):
    def test_plan_has_the_shared_shape(self):
        out = plan()
        self.assertTrue(out["ok"])
        self.assertEqual(out["project_id"], "tgt-proj")
        self.assertEqual(out["project_name"], "Target demo")
        ch = out["changes"][0]
        for k in CHANGE_KEYS:
            self.assertIn(k, ch)
        self.assertEqual((ch["status"], ch["kind"], ch["tool"], ch["live_impact"]),
                         ("ready", "create", "clone_scenario", "none"))
        self.assertEqual(ch["undo"], [])
        self.assertIn("undo_note", ch)
        self.assertEqual(out["batches"], [[1]])
        self.assertEqual(ch["after"]["status"], "draft")
        self.assertEqual(ch["after"]["name"], "Browse abandonment (clone 2026-11-05)")

    def test_every_dependency_is_passed_and_none_is_replaced(self):
        out = plan()
        items = out["changes"][0]["payload"]["items"]
        self.assertEqual(sorted(i["id"] for i in items), ["agg-demo-1", "exp-demo-1", "rec-demo-1", "src-scenario-0001"])
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id["agg-demo-1"]["on_conflict"], "use_old")
        self.assertNotIn("on_conflict", by_id["rec-demo-1"])
        self.assertNotIn("on_conflict", by_id["src-scenario-0001"])
        self.assertNotIn("replace", json.dumps(out["changes"][0]["payload"]))
        self.assertIn("dependency_differs", checks(out["changes"][0]["warnings"]))

    def test_same_project_duplicates_the_scenario_and_reuses_the_rest(self):
        out = plan(preview="preview_same.json", target="src-proj", target_name="Source demo")
        self.assertEqual(out["mode"], "same_project")
        by_id = {i["id"]: i for i in out["changes"][0]["payload"]["items"]}
        self.assertEqual(by_id["src-scenario-0001"]["on_conflict"], "duplicate")
        for dep in ("agg-demo-1", "exp-demo-1", "rec-demo-1", "seg-demo-1"):
            self.assertEqual(by_id[dep]["on_conflict"], "use_old")
        self.assertEqual(out["fix_list"], [])
        self.assertNotIn("dependency_differs", checks(out["changes"][0]["warnings"]))

    def test_override_duplicate_and_refuse_replace(self):
        out = plan(extra=("--on-conflict", "agg-demo-1=duplicate"))
        by_id = {i["id"]: i for i in out["changes"][0]["payload"]["items"]}
        self.assertEqual(by_id["agg-demo-1"]["on_conflict"], "duplicate")
        self.assertIn("duplicate_dependency", checks(out["changes"][0]["warnings"]))
        r = plan(extra=("--on-conflict", "agg-demo-1=replace"), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("never uses it", r.stdout)
        r = plan(extra=("--on-conflict", "nope=use_old"), ok=False)
        self.assertEqual(r.returncode, 1)
        r = plan(extra=("--on-conflict", "rec-demo-1=duplicate"), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("doesn't have yet", r.stdout)
        r = plan(preview="preview_same.json", target="src-proj", target_name="Source demo",
                 extra=("--on-conflict", "src-scenario-0001=use_old"), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("always duplicated", r.stdout)


class Blockers(unittest.TestCase):
    def test_name_taken_blocks(self):
        out = plan(extra=("--today", "2026-11-04"))
        ch = out["changes"][0]
        self.assertEqual(ch["status"], "blocked")
        self.assertIn("name_taken", checks(ch["problems"]))
        self.assertEqual(out["batches"], [])

    def test_empty_suffix_blocks(self):
        out = plan(extra=("--name-suffix", ""))
        self.assertIn("no_suffix", checks(out["changes"][0]["problems"]))

    def test_preview_for_another_scenario_blocks(self):
        out = plan(preview="preview_other.json")
        self.assertIn("preview_mismatch", checks(out["changes"][0]["problems"]))

    def test_access_error_stops_and_strips_urls(self):
        r = run("plan", "--source", FX / "error_access.json", "--preview", FX / "preview_cross.json",
                "--source-project-id", "a", "--source-project-name", "A", "--project-id", "b", "--project-name", "B",
                "--source-org", "Org", "--target-org", "Org",
                "--target-scenarios", FX / "target_scenarios.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project, account or access", r.stdout)
        self.assertNotIn("auth_key", r.stdout)
        self.assertNotIn("FAKE", r.stdout)


class FixList(unittest.TestCase):
    def test_every_unresolved_reference_is_listed(self):
        fixes = {(f["kind"], f["ref"]): f for f in plan()["fix_list"]}
        expected = {("consent_category", "newsletter"), ("integration", "int-demo-1"), ("customer_property", "loyalty_tier"),
                    ("event", "purchase"), ("event_property", "view_item.category_level_1"),
                    ("frequency_policy", "smart-policy"), ("id_reference", "segmentation seg-demo-1"),
                    ("project_variable", "brand_name"), ("engine_catalog", "Similar items (catalog 'products_eu')")}
        self.assertEqual(set(fixes), expected)
        self.assertEqual(fixes[("consent_category", "newsletter")]["priority"], "high")
        self.assertEqual(fixes[("event", "purchase")]["priority"], "medium")
        for f in fixes.values():
            self.assertTrue(f["fix"])
        # things that resolve are not listed
        self.assertNotIn(("consent_category", "sms"), fixes)
        self.assertNotIn(("catalog", "products"), fixes)
        self.assertNotIn(("catalog", "get"), fixes)

    def test_fix_list_is_sorted_by_priority(self):
        order = [f["priority"] for f in plan()["fix_list"]]
        self.assertEqual(order, sorted(order, key=["high", "medium", "low"].index))

    def test_missing_trigger_event_is_high(self):
        lookups = tuple(x for x in TARGET_LOOKUPS)
        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp) / "events.json"
            ev.write_text(json.dumps({"success": True, "data": {"events": [{"type": "purchase"}]}}) + "\n",
                          encoding="utf-8")
            lookups = list(lookups)
            lookups[lookups.index(FX / "target_events.json")] = ev
            fixes = plan(lookups=lookups)["fix_list"]
        trig = [f for f in fixes if f["kind"] == "trigger_event"]
        self.assertEqual(len(trig), 1)
        self.assertEqual(trig[0]["priority"], "high")
        self.assertFalse([f for f in fixes if f["kind"] == "event" and f["ref"] == "view_item"])

    def test_missing_lookups_are_reported_not_checked(self):
        out = plan(lookups=())
        self.assertEqual(out["fix_list"][0]["kind"], "id_reference")
        self.assertIn("consent_category", out["not_checked"])
        self.assertIn("engine_catalog", out["not_checked"])
        self.assertIn("not_checked", checks(out["changes"][0]["warnings"]))


class Privacy(unittest.TestCase):
    def test_webhook_secrets_and_editor_names_never_printed(self):
        r = run("plan", "--source", FX / "source.json", "--preview", FX / "preview_cross.json",
                "--source-project-id", "src-proj", "--source-project-name", "Source demo", "--project-id", "tgt-proj",
                "--project-name", "Target demo", "--source-org", "Example Org", "--target-org", "Example Org",
                "--target-scenarios", FX / "target_scenarios.json",
                "--today", "2026-11-05", *TARGET_LOOKUPS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for secret in ("FAKE", "hooks.example", "Authorization", "Example Editor"):
            self.assertNotIn(secret, r.stdout)
        out = json.loads(r.stdout)
        self.assertEqual(out["webhooks"], [{"node_id": 5, "name": "Notify CRM", "has_headers": True, "has_body": True,
                                            "has_auth_integration": True}])
        self.assertIn("webhook_tokens", checks(out["changes"][0]["warnings"]))


class FindAndVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        r = run("plan", "--source", FX / "source.json", "--preview", FX / "preview_cross.json",
                "--source-project-id", "src-proj", "--source-project-name", "Source demo", "--project-id", "tgt-proj",
                "--project-name", "Target demo", "--source-org", "Example Org", "--target-org", "Example Org",
                "--target-scenarios", FX / "target_scenarios.json",
                "--today", "2026-11-05", "--out", self.dir / "plan.json", cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.plan = self.dir / "plan.json"
        self.assertTrue(self.plan.read_text(encoding="utf-8").endswith("}\n"))

    def tearDown(self):
        self.tmp.cleanup()

    def readback(self, **changes):
        src = json.loads((FX / "source.json").read_text(encoding="utf-8"))["result"]["data"]
        rec = dict(src, _id="new-scenario-1", name="Browse abandonment (clone 2026-11-05)", status="draft")
        rec.update(changes)
        p = self.dir / "readback.json"
        p.write_text(json.dumps({"result": {"success": True, "data": rec}}) + "\n", encoding="utf-8")
        return p

    def verify(self, path):
        r = run("verify", "--plan", self.plan, "--readback", f"1={path}")
        return r

    def test_find_exact_and_since(self):
        r = run("find", "--plan", self.plan, "--scenarios", FX / "target_scenarios_after.json")
        out = json.loads(r.stdout)
        self.assertEqual(out["state"], "one")
        self.assertEqual(out["found"][0]["id"], "tgt-scenario-3")
        r = run("find", "--plan", self.plan, "--scenarios", FX / "target_scenarios_after.json", "--since", "1800000000")
        out = json.loads(r.stdout)
        self.assertEqual(out["state"], "several")
        self.assertEqual([f["match"] for f in out["found"]], ["exact_name", "created_since"])
        r = run("find", "--plan", self.plan, "--scenarios", FX / "target_scenarios.json")
        self.assertEqual(json.loads(r.stdout)["state"], "none")

    def test_verify_in_place(self):
        out = json.loads(self.verify(self.readback()).stdout)
        self.assertEqual(out["results"][0]["state"], "in_place")
        self.assertEqual(out["results"][0]["scenario_id"], "new-scenario-1")
        self.assertNotIn("alert", out["results"][0])

    def test_verify_inactive_is_fine_active_alerts(self):
        out = json.loads(self.verify(self.readback(status="inactive")).stdout)
        self.assertEqual(out["results"][0]["state"], "in_place")
        out = json.loads(self.verify(self.readback(status="active")).stdout)
        res = out["results"][0]
        self.assertEqual(res["state"], "not_in_place")
        self.assertIn("alert", res)

    def test_verify_lost_steps_and_wrong_name(self):
        src = json.loads((FX / "source.json").read_text(encoding="utf-8"))["result"]["data"]
        out = json.loads(self.verify(self.readback(nodes=src["nodes"][:4], name="Other")).stdout)
        fields = {m["field"] for m in out["results"][0]["mismatches"]}
        self.assertTrue({"name", "node_count", "node_types", "webhook_count"} <= fields)

    def test_verify_source_id_is_not_a_clone(self):
        out = json.loads(self.verify(self.readback(_id="src-scenario-0001")).stdout)
        self.assertIn("scenario_id", {m["field"] for m in out["results"][0]["mismatches"]})

    def test_verify_not_found_and_access_error(self):
        out = json.loads(self.verify(FX / "not_found.json").stdout)
        self.assertEqual(out["results"][0]["state"], "not_in_place")
        self.assertIn("run find", out["results"][0]["note"])
        r = self.verify(FX / "error_access.json")
        self.assertEqual(r.returncode, 1)

    def test_bad_out_path_fails_cleanly(self):
        r = run("find", "--plan", self.plan, "--scenarios", FX / "target_scenarios.json",
                "--out", self.dir / "missing" / "x.json")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])


class CrossOrganisation(unittest.TestCase):
    def test_cross_org_blocks_until_confirmed_and_webhooks_always_block(self):
        out = plan(orgs=("Org A", "Org B"))
        ch = out["changes"][0]
        self.assertEqual(ch["status"], "blocked")
        self.assertIn("cross_org_unconfirmed", checks(ch["problems"]))
        self.assertIn("cross_org_webhooks", checks(ch["problems"]))
        self.assertTrue(out["summary"]["cross_org"])
        self.assertEqual((out["source_org"], out["target_org"]), ("Org A", "Org B"))
        out = plan(orgs=("Org A", "Org B"), extra=("--cross-org-confirmed",))
        probs = checks(out["changes"][0]["problems"])
        self.assertNotIn("cross_org_unconfirmed", probs)
        self.assertIn("cross_org_webhooks", probs)

    def test_cross_org_without_webhooks_is_ready_once_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = json.loads((FX / "source.json").read_text(encoding="utf-8"))
            src["result"]["data"]["nodes"] = [n for n in src["result"]["data"]["nodes"] if "webhook" not in n["type"]]
            path = Path(tmp) / "source_nohook.json"
            path.write_text(json.dumps(src) + "\n", encoding="utf-8")
            out = plan(orgs=("Org A", "Org B"), source=path)
            self.assertEqual(checks(out["changes"][0]["problems"]), ["cross_org_unconfirmed"])
            out = plan(orgs=("Org A", "Org B"), source=path, extra=("--cross-org-confirmed",))
            self.assertEqual(out["changes"][0]["status"], "ready")

    def test_same_org_compared_case_insensitively(self):
        out = plan(orgs=("Example Org", " example  org "))
        self.assertFalse(out["cross_org"])
        self.assertEqual(out["changes"][0]["status"], "ready")

    def test_same_project_in_two_orgs_fails(self):
        r = plan(preview="preview_same.json", target="src-proj", target_name="Source demo", orgs=("A", "B"), ok=False)
        self.assertEqual(r.returncode, 1)


class StalePreview(unittest.TestCase):
    def test_same_project_with_cross_project_preview_blocks(self):
        out = plan(preview="preview_cross.json", target="src-proj", target_name="Source demo")
        ch = out["changes"][0]
        self.assertEqual(ch["status"], "blocked")
        self.assertIn("stale_preview", checks(ch["problems"]))
        self.assertEqual(out["batches"], [])

    def test_same_project_dependency_missing_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = json.loads((FX / "preview_same.json").read_text(encoding="utf-8"))
            prev["dependencies"][0]["exists"] = False
            path = Path(tmp) / "preview.json"
            path.write_text(json.dumps(prev) + "\n", encoding="utf-8")
            out = plan(preview=path, target="src-proj", target_name="Source demo")
        self.assertIn("stale_preview", checks(out["changes"][0]["problems"]))

    def test_every_existing_dependency_gets_an_explicit_on_conflict(self):
        for kw in ({}, {"preview": "preview_same.json", "target": "src-proj", "target_name": "Source demo"}):
            out = plan(**kw)
            for item in out["changes"][0]["payload"]["items"]:
                prev = json.loads((FX / (kw.get("preview") or "preview_cross.json")).read_text(encoding="utf-8"))
                exists = {d["id"]: d["exists"] for d in prev["dependencies"]}
                if exists[item["id"]]:
                    self.assertIn(item.get("on_conflict"), ("use_old", "duplicate"))


class Rules(unittest.TestCase):
    def test_every_rules_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))
        self.assertTrue(rules["about"])

    def test_replace_is_never_allowed(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertNotIn("replace", rules["allowed_on_conflict"])
        self.assertIn("replace", rules["forbidden_on_conflict"])

    def test_fixtures_end_with_newline(self):
        for p in FX.iterdir():
            self.assertTrue(p.read_bytes().endswith(b"\n"), p.name)


if __name__ == "__main__":
    unittest.main()
