"""Tests for engagement-dependency-map's engagement_dependency_map.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-dependency-map"
SCRIPT = SKILL / "scripts/engagement_dependency_map.py"
FIX = ROOT / "tests/fixtures/engagement/engagement-dependency-map"

LISTS = ["aggregate=aggregates.json", "expression=expressions.json", "segmentation=segmentations.json",
         "customer_filter=customer_filters.json", "scenario=scenarios.json", "email=email_campaigns.json",
         "project_variable=project_variables.json"]
DETAILS = ["expression=expression_spend_band.json", "scenario=scenario_vip_flow.json",
           "scenario=scenario_draft_flow.json", "email=email_weekly_news.json"]


def run(*args, cwd=None):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd or tmp, capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        if cwd is None:
            assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def inputs():
    args = []
    for pair in LISTS:
        kind, name = pair.split("=", 1)
        args += ["--list", f"{kind}={FIX / name}"]
    for pair in DETAILS:
        kind, name = pair.split("=", 1)
        args += ["--detail", f"{kind}={FIX / name}"]
    return args


def full():
    r = run(*inputs(), "--targets", FIX / "candidates.json", "--denied", "sms")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def target(out, kind, name):
    return next(t for t in out["targets"] if t["kind"] == kind and t["name"] == name)


def names(items):
    return [i["name"] for i in items]


class DependencyMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = full()

    def test_indirect_chain_to_live_scenario_blocks(self):
        t = target(self.out, "aggregate", "Total spend 365d")
        self.assertEqual((t["verdict"], t["priority"]), ("blocked", "high"))
        vip = next(d for d in t["dependants"] if d["name"] == "VIP flow")
        self.assertEqual(vip["hops"], 3)
        self.assertTrue(vip["live"])
        self.assertEqual(vip["via"], ["segmentation 'High spenders'", "expression 'Spend band'"])
        expr = next(d for d in t["dependants"] if d["name"] == "Spend band")
        self.assertEqual(expr["how"], ["id", "used_by"])
        self.assertEqual(expr["where"], "variables[0].attribute.id")
        self.assertEqual(t["counts"]["reporting"], 2)

    def test_consent_and_variable_found_by_name_and_template(self):
        c = target(self.out, "consent", "newsletter")
        self.assertEqual(c["verdict"], "blocked")
        self.assertEqual(c["dependants"][0]["how"], ["name"])
        v = target(self.out, "project_variable", "brand_name")
        self.assertEqual(v["verdict"], "blocked")
        self.assertEqual(v["dependants"][0]["how"], ["template"])
        self.assertEqual(v["dependants"][0]["where"], "subject")

    def test_draft_dependant_is_check_first(self):
        t = target(self.out, "customer_filter", "Old filter")
        self.assertEqual((t["verdict"], t["priority"]), ("check first", "medium"))
        self.assertIs(t["dependants"][0]["live"], False)

    def test_unknown_status_is_not_safe(self):
        t = target(self.out, "aggregate", "Mystery aggregate")
        self.assertEqual(t["verdict"], "check first")
        self.assertEqual(t["counts"]["status_unknown"], 1)

    def test_no_dependants(self):
        for kind, name in (("aggregate", "Old test aggregate"), ("project_variable", "unused_var")):
            t = target(self.out, kind, name)
            self.assertEqual((t["verdict"], t["priority"]), ("no dependants found", "low"))

    def test_deletion_order_leaves_first_and_cycles_together(self):
        order = self.out["deletion_order"]
        self.assertEqual([names(s) for s in order["steps"]],
                         [["Old test aggregate", "Legacy expression", "unused_var"], ["Legacy aggregate"]])
        self.assertEqual(names(order["together"]), ["Loop A", "Loop B"])
        self.assertEqual(sorted(names(order["review_first"])), ["Mystery aggregate", "Old filter"])
        self.assertEqual(sorted(names(order["blocked"])), ["High spenders", "Total spend 365d", "brand_name", "newsletter"])

    def test_coverage_and_denied(self):
        self.assertEqual(self.out["checked"]["denied"], ["sms"])
        self.assertIn("banner", self.out["checked"]["not_checked"])
        self.assertNotIn("sms", self.out["checked"]["not_checked"])

    def test_never_prints_editor_names(self):
        text = json.dumps(self.out)
        self.assertNotIn("Pat Example", text)
        self.assertNotIn("pat.example@", text)

    def test_deterministic(self):
        self.assertEqual(full(), self.out)

    def test_target_resolves_by_name_and_cycle_terminates(self):
        r = run(*inputs(), "--target", "segmentation=Loop A")
        self.assertEqual(r.returncode, 0, r.stderr)
        t = json.loads(r.stdout)["targets"][0]
        self.assertEqual([d["name"] for d in t["dependants"]], ["Loop B"])

    def test_tool_error_is_not_nothing_found(self):
        r = run("--list", f"aggregate={FIX / 'denied.json'}", "--target", "aggregate=x")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])
        self.assertIn("don't treat it as 'nothing found'", r.stdout)

    def test_bad_input(self):
        self.assertEqual(run("--list", "aggregate", "--target", "aggregate=x").returncode, 1)
        self.assertEqual(run("--list", f"widget={FIX / 'aggregates.json'}", "--target", "aggregate=x").returncode, 1)
        self.assertEqual(run("--list", f"aggregate={FIX / 'nope.json'}", "--target", "aggregate=x").returncode, 1)
        self.assertEqual(run(*inputs()).returncode, 1)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(*inputs(), "--target", "aggregate=Old test aggregate", "--out", "map.json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads((Path(tmp) / "map.json").read_text(encoding="utf-8")), json.loads(r.stdout))
            bad = run(*inputs(), "--target", "aggregate=x", "--out", str(Path(tmp) / "missing" / "m.json"), cwd=tmp)
            self.assertEqual(bad.returncode, 1)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertTrue(rules.get("about"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(sorted(keys - set(rules["notes"])), [])
        self.assertEqual(sorted(set(rules["notes"]) - keys), [])


if __name__ == "__main__":
    unittest.main()
