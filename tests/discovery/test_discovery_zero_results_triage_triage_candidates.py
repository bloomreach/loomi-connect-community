import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-zero-results-triage"
SCRIPT = SKILL / "scripts/triage_candidates.py"
FIX = ROOT / "tests/fixtures/discovery"
CONTRACT = FIX / "zero_results/contract"

# Import without writing __pycache__ next to the script: skill folders may be read-only.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("triage_candidates", SCRIPT)
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)


def run(*args):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, timeout=60)


def contract_args():
    c = CONTRACT
    return ["--no-results", c / "no_results.json", "--no-revenue", c / "no_revenue.json", "--top", c / "top.json",
            "--synonyms", c / "synonyms.json", "--redirects", c / "redirects.json"]


def m(query, sessions=50, views=0, revenue=0.0):
    return {"query": query, "sessions": float(sessions), "prev_sessions": 0.0, "views": float(views), "revenue": float(revenue)}


SELLERS = [m("t shirt", 1000, 10, 3000), m("jeans", 800, 10, 2400), m("sneakers", 500, 10, 1500)]


def classify(query, kind="no_results", sessions=50, synonyms=(), redirects=()):
    return tc.classify(m(query, sessions), kind, SELLERS, tc.synonym_map(list(synonyms)), set(redirects),
                       tc.RULES, tc.page_intent(tc.RULES))


class TriageCandidatesTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_contract_fixture_matches_the_script(self):
        """contract/expected.json is what apps that port these rules test against, so it must stay the script's output."""
        p = run(*contract_args())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), json.loads((CONTRACT / "expected.json").read_text()),
                         "the rules changed: regenerate tests/fixtures/discovery/zero_results/contract/expected.json")

    def test_contract_covers_every_class(self):
        expected = json.loads((CONTRACT / "expected.json").read_text())
        self.assertEqual({r["class"] for r in expected["queries"]}, set(tc.REASONS))

    def test_rules_file_is_complete(self):
        rules = json.loads((SKILL / "references/rules.json").read_text())
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})

    def test_out_writes_to_the_working_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run([sys.executable, str(SCRIPT), *map(str, contract_args()), "--out", "triage.json"],
                               cwd=tmp, capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads((Path(tmp) / "triage.json").read_text())["summary"]["dead_ends"], 19)
            self.assertTrue(json.loads(p.stdout)["ok"])

    def test_error_response_stops(self):
        c = CONTRACT
        p = run("--no-results", FIX / "denied.json", "--no-revenue", c / "no_revenue.json", "--top", c / "top.json")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(json.loads(p.stdout)["ok"])

    # One test per class.
    def test_noise(self):
        self.assertEqual(classify("hoodie", sessions=tc.RULES["min_sessions"] - 1)[0], "noise")
        self.assertEqual(classify("x")[0], "noise")
        self.assertEqual(classify("12-345")[0], "noise")

    def test_covered_by_redirect_beats_page_intent(self):
        self.assertEqual(classify("Gift Card", redirects={"gift card"})[0], "covered_by_redirect")

    def test_page_intent_only_for_no_results(self):
        self.assertEqual(classify("store hours")[0], "page_intent")
        self.assertEqual(classify("giftcard")[0], "page_intent")
        self.assertEqual(classify("returns policy", kind="no_sales")[0], "none")
        self.assertEqual(classify("appliances")[0], "none", "whole words only")

    def test_spelling_twin(self):
        self.assertEqual(classify("tshirt")[1]["query"], "t shirt")
        self.assertEqual(classify("jeens")[1]["query"], "jeans")
        self.assertEqual(classify("sneekerss")[1]["query"], "sneakers")
        self.assertEqual(classify("sneaker", kind="no_sales")[0], "spelling_twin")
        self.assertEqual(classify("jeanz2")[0], "none", "two edits on a short word is too far")
        self.assertEqual(classify("jean")[0], "spelling_twin")
        self.assertEqual(classify("tee")[0], "none", "too short to match")

    def test_synonym_no_results(self):
        syn = [{"sourceSynonym": "capris", "targetSynonym": "cropped trousers"}]
        self.assertEqual(classify("capris", synonyms=syn)[0], "synonym_no_results")

    def test_noop_synonym(self):
        syn = [{"sourceSynonym": "Corset", "targetSynonym": "corset, CORSET"}]
        self.assertEqual(classify("corset", synonyms=syn)[0], "noop_synonym")

    def test_disabled_synonym_is_ignored(self):
        syn = [{"sourceSynonym": "bikini", "targetSynonym": "swimwear", "enabled": False}]
        self.assertEqual(classify("bikini", synonyms=syn)[0], "none")

    def test_no_sales_skips_synonym_checks(self):
        syn = [{"sourceSynonym": "capris", "targetSynonym": "cropped trousers"}]
        self.assertEqual(classify("capris", kind="no_sales", synonyms=syn)[0], "none")

    def test_no_revenue_row_without_views_is_a_dead_end(self):
        out = tc.triage([], [m("track my order", 40, views=0), m("linen shirt", 40, views=9)], SELLERS, [], [], tc.RULES)
        kinds = {r["query"]: r["kind"] for r in out["queries"]}
        self.assertEqual(kinds, {"track my order": "no_results", "linen shirt": "no_sales"})

    def test_at_stake_uses_median_revenue_per_session(self):
        out = tc.triage([m("flippers", 100)], [], SELLERS, [], [], tc.RULES)
        self.assertEqual(out["typical_revenue_per_session"], 3.0)
        self.assertEqual(out["queries"][0]["revenue_at_stake"], 300.0)

    def test_numbers(self):
        self.assertEqual(tc.number("$1,234.50"), 1234.5)
        self.assertEqual(tc.number("(12.00)"), -12.0)
        self.assertIsNone(tc.number("NA"))
        self.assertIsNone(tc.number(True))


if __name__ == "__main__":
    unittest.main()
