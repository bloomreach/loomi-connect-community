import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-platform/skills/weekly-ecommerce-briefing/scripts/briefing_numbers.py"
FIX = ROOT / "tests/fixtures/platform/briefing"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True)


def load_script():
    import importlib.util
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # never write __pycache__ into the skill folder
    try:
        spec = importlib.util.spec_from_file_location("briefing_numbers", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = old


class BriefingNumbersTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_ok_card(self):
        p = run("--overall", FIX / "overall.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["kpis"]["overall"]["this"]["revenue"], 100000.0)
        self.assertNotIn("missing_values", out)

    def test_na_does_not_crash_and_is_reported(self):
        p = run("--overall", FIX / "overall_na.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["kpis"]["overall"]["this"]["revenue"], 0.0)
        self.assertEqual(out["missing_values"]["count"], 2)
        self.assertTrue(all("overall_na.json current." in m for m in out["missing_values"]["counted_as_zero"]))

    def test_error_response_stops(self):
        p = run("--overall", FIX / "overall.json", "--queries", FIX / "queries_denied.json")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        out = json.loads(p.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("queries_denied.json: Loomi Connect returned an error: [ACCESS_DENIED]", out["error"])


    def test_contract_fixture_matches_the_script(self):
        """contract/expected.json is what apps that port these rules test against, so it must stay the script's output."""
        c = FIX / "contract"
        p = run("--overall", c / "overall.json", "--search", c / "search.json", "--queries", c / "queries.json",
                "--dead-ends", c / "dead_ends.json", "--categories", c / "categories.json",
                "--products", c / "products.json", "--brands", c / "brands.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), json.loads((c / "expected.json").read_text()),
                         "the rules changed: regenerate tests/fixtures/platform/briefing/contract/expected.json")

    def test_a_search_with_a_few_product_views_is_not_a_dead_end(self):
        bn = load_script()
        rows = [{"query": f"q{i}", "browse_sessions": 1000, "prev_browse_sessions": 1000, "visits": 1000,
                 "revenue": 500, "prev_revenue": 500, "conversion_rate": "2%", "bounce_rate": "40%",
                 "product_page_views": 900, "aov": 50, "rpv": 0.5} for i in range(5)]
        rows.append({"query": "almost-dead", "browse_sessions": 1000, "prev_browse_sessions": 1000, "visits": 1000,
                     "revenue": 0, "prev_revenue": 0, "conversion_rate": "0%", "bounce_rate": "95%",
                     "product_page_views": 3, "aov": 0, "rpv": 0})
        out = bn.top_and_issues(rows, "query", "browse_sessions", 30, 10, 20)
        reasons = {i["name"]: i["reasons"] for i in out["issues"]}
        self.assertIn("almost-dead", reasons)  # still an issue (no revenue), but not "no product views"
        self.assertFalse(any(r.startswith("dead end") for r in reasons["almost-dead"]))

    def test_revenue_drops_and_gains_leave_out_unchanged_queries(self):
        bn = load_script()
        rows = [{"query": n, "browse_sessions": 100, "prev_browse_sessions": 100, "revenue": r1, "prev_revenue": r0}
                for n, r1, r0 in (("down-a", 0, 200), ("down-b", 0, 100), ("flat", 50, 50), ("up", 80, 30))]
        out = bn.query_movers(rows, 0, 30, 5)
        self.assertEqual([i["query"] for i in out["biggest_revenue_drop"]], ["down-a", "down-b"])
        self.assertEqual([i["query"] for i in out["biggest_revenue_gain"]], ["up"])

    def test_rules_file_is_complete(self):
        rules = json.loads((SCRIPT.parent.parent / "references/rules.json").read_text())
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})


if __name__ == "__main__":
    unittest.main()
