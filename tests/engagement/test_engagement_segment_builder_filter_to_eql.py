"""Tests for engagement-segment-builder/scripts/filter_to_eql.py.

contract/expected.json is the script's real output for contract/cases.json (run with --with-total).
Apps that port the translation (loomi-connect-openui's filterEql) test against the same files.
After changing a rule on purpose, regenerate it:

    python3 tests/engagement/test_engagement_segment_builder_filter_to_eql.py --regenerate
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-engagement/skills/engagement-segment-builder/scripts/filter_to_eql.py"
CONTRACT = ROOT / "tests/fixtures/engagement/segment_builder/contract"
SCENARIO = ROOT / "tests/fixtures/engagement/scenario_splits.json"


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=cwd or tmp, capture_output=True, text=True)


def translate(obj, *args):
    """Run the script on a JSON value saved to a file, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "filter.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        r = run(p, *args, cwd=tmp)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def contract_output():
    cases = json.loads((CONTRACT / "cases.json").read_text(encoding="utf-8"))
    return [{"name": c["name"], **translate(c["filter"], "--with-total")} for c in cases]


def prop(p, kind, op, value=None):
    ops = [] if value is None else [{"type": "constant", "value": value}]
    return {"type": "attribute", "attribute": {"type": "property", "property": p},
            "constraint": {"type": kind, "operator": op, "operands": ops}}


PURCHASE_30 = {"type": "funnel_steps", "steps": [{"type": "purchase", "filter": []}],
               "date_filter": {"enabled": True, "absolute": False, "duration": {"count": 30, "units": "days"}}}


class ContractTest(unittest.TestCase):
    def test_contract_fixture_matches_the_script(self):
        """expected.json is what the app's port is tested against, so it must stay the script's output."""
        want = json.loads((CONTRACT / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(contract_output(), want,
                         "the translation changed: regenerate expected.json (see this file's docstring)")

    def test_cases_cover_every_rule_kind(self):
        text = (CONTRACT / "cases.json").read_text(encoding="utf-8")
        for kind in ['"string"', '"number"', '"boolean"', '"date"', '"consent"', '"id"', '"funnel_steps"',
                     '"segmentation"', '"prediction"', '"aggregate"', '"expression"', '"embedded_aggregate"']:
            self.assertIn(kind, text)
        names = [c["name"] for c in json.loads(text)]
        self.assertEqual(len(names), len(set(names)), "case names must be unique")


class TranslationTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_formula_kept(self):
        r = translate({"filters": [prop("email", "string", "has value"), PURCHASE_30,
                                   {"type": "attribute", "attribute": {"type": "consent", "category": "newsletter"},
                                    "constraint": {"type": "boolean", "operator": "is", "value": "true"}}],
                       "formula": "F0&!F1&F2"})
        self.assertEqual(r["unsupported"], [])
        self.assertEqual(r["eql"], '(customer."email" has value) and  not (exists[event "purchase" in last 30 days])'
                                   ' and (has consent "newsletter")')

    def test_saved_definitions_are_named_not_sized(self):
        seg = {"type": "attribute", "attribute": {"type": "segmentation", "id": "x"}, "constraint": {}}
        r = translate({"filters": [seg, prop("a", "string", "equals", "x")], "formula": "F0|F1"})
        self.assertEqual(r, {"eql": None, "unsupported": ["segments"], "query": None})

    def test_custom_formula_refused(self):
        r = translate({"filters": [prop("a", "string", "equals", "x")], "formula": "F0) or (1"})
        self.assertEqual(r["unsupported"], ["its custom formula"])

    def test_values_cant_close_their_quote(self):
        r = translate({"filters": [prop("name", "string", "equals", 'a" or customer.x = "b\\')], "formula": "F0"})
        self.assertEqual(r["eql"], '(customer."name" = "a or customer.x = b")')

    def test_everyone(self):
        r = translate({"filters": [], "formula": ""})
        self.assertEqual(r["eql"], None)
        self.assertEqual(r["query"], "select count customers by customer.country grouping top 1 with null")

    def test_query_forms(self):
        f = {"filters": [PURCHASE_30], "formula": "F0"}
        self.assertEqual(translate(f, "--by", "loyalty-tier")["query"],
                         'select count customers by customer."loyalty-tier" grouping top 1 with null'
                         ' customers matching (exists[event "purchase" in last 30 days])')
        self.assertEqual(translate(f, "--with-total")["query"],
                         'select count customers matching (exists[event "purchase" in last 30 days]),'
                         ' count customers by customer.country grouping top 1 with null')

    def test_reads_a_condition_node_and_a_wrapped_response(self):
        node = {"id": "4", "type": "condition", "customer_filter": {"filters": [PURCHASE_30], "formula": "F0"}}
        self.assertEqual(translate(node)["eql"], '(exists[event "purchase" in last 30 days])')
        self.assertEqual(translate({"success": True, "data": node})["eql"], '(exists[event "purchase" in last 30 days])')

    def test_picks_a_condition_from_a_scenario(self):
        cond = lambda i, p: {"id": i, "type": "condition", "customer_filter": {"filters": [prop(p, "string", "has value")], "formula": "F0"}}
        scenario = {"success": True, "data": {"name": "x", "nodes": [{"id": "1", "type": "now-trigger"}, cond("2", "email"), cond("3", "phone")]}}
        self.assertEqual(translate(scenario, "--node", "3")["eql"], '(customer."phone" has value)')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.json"
            p.write_text(json.dumps(scenario))
            r = run(p, cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("pick one condition with --node", r.stderr)
        self.assertIn("2, 3", r.stderr)

    def test_scenario_without_conditions(self):
        r = run(SCENARIO)
        self.assertEqual(r.returncode, 1)
        self.assertIn("nodes with a customer filter: none", r.stderr)

    def test_error_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "e.json"
            p.write_text(json.dumps({"success": False, "error": "[ACCESS_DENIED]"}))
            r = run(p, cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", r.stderr)

    def test_out_writes_only_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "f.json"
            src.write_text(json.dumps({"filters": [PURCHASE_30], "formula": "F0"}))
            r = run(src, "--out", Path(tmp) / "eql.json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "")
            self.assertEqual(json.loads((Path(tmp) / "eql.json").read_text())["unsupported"], [])
            self.assertEqual(sorted(x.name for x in Path(tmp).iterdir()), ["eql.json", "f.json"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--regenerate"]:
        out = contract_output()
        (CONTRACT / "expected.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {len(out)} cases to {CONTRACT / 'expected.json'}")
    else:
        unittest.main()
