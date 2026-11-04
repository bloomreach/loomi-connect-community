"""Tests for discovery-product-visibility's visibility_explain.py. The fixtures in
tests/fixtures/discovery/product_visibility/ are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-product-visibility"
SCRIPT = SKILL / "scripts/visibility_explain.py"
FX = ROOT / "tests/fixtures/discovery/product_visibility"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def kinds(out):
    return [(c["kind"], c["finding"]) for c in out["causes"]]


class VisibilityExplainTest(unittest.TestCase):
    def test_ranked_with_boosts_above_and_weak_text_match(self):
        code, out, _ = run("--pid", "P10", "--grid", FX / "grid_page1.json")
        self.assertEqual(code, 0)
        self.assertEqual((out["status"], out["position"], out["on_page_one"]), ("ranked", 13, True))  # banner skipped
        found = kinds(out)
        self.assertTrue(any(k == "merchandising" and "3 product(s) above it are boosted" in f for k, f in found))
        self.assertTrue(any(k == "data" and "Weaker text match" in f for k, f in found))
        boost = next(c for c in out["causes"] if "boosted" in c["finding"])
        self.assertEqual(boost["evidence"]["rules"], ["900001"])
        self.assertEqual(out["scores"]["relevance"], 30.0)

    def test_buried_product(self):
        _, out, _ = run("--pid", "P05", "--grid", FX / "grid_page1.json")
        self.assertTrue(any(c["kind"] == "merchandising" and "buries" in c["finding"] for c in out["causes"]))

    def test_performance_gap(self):
        _, out, _ = run("--pid", "P12", "--grid", FX / "grid_page1.json")
        self.assertTrue(any(c["kind"] == "ranking" and "Lower performance" in c["finding"] for c in out["causes"]))

    def test_second_page_in_any_order(self):
        _, out, _ = run("--pid", "P42", "--grid", FX / "grid_page2.json", "--grid", FX / "grid_page1.json")
        self.assertEqual((out["status"], out["position"], out["on_page_one"]), ("ranked", 33, False))
        self.assertEqual(out["products_fetched"], 35)

    def test_nothing_holding_it_back(self):
        _, out, _ = run("--pid", "Q30", "--grid", FX / "grid_plain.json")
        self.assertEqual(out["position"], 30)
        self.assertEqual(kinds(out), [("ranking", "It isn't held back by a rule or a weak match: the products above simply score higher.")])

    def test_matched_but_not_fetched(self):
        _, out, _ = run("--pid", "P99", "--grid", FX / "grid_page1.json", "--match-check", FX / "match_check_found.json")
        self.assertEqual(out["status"], "matched_not_fetched")
        self.assertTrue(any("deeper than the 30 products fetched" in n for n in out["not_checked"]))

    def test_excluded_by_rule_with_catalog_detail(self):
        _, out, _ = run("--pid", "P77", "--grid", FX / "grid_page1.json", "--match-check", FX / "match_check_empty.json",
                        "--rules-off", FX / "rules_off_found.json", "--catalog", FX / "catalog_unavailable.json",
                        "--query", "rain jacket")
        self.assertEqual(out["status"], "excluded_by_rule")
        found = kinds(out)
        self.assertTrue(any(k == "merchandising" and "removes it" in f for k, f in found))
        self.assertTrue(any(k == "recall" and "unavailable" in f for k, f in found))
        cat = next(c for c in out["causes"] if "excludes one of its categories" in c["finding"])
        self.assertEqual(cat["evidence"]["exclusions"], [{"rule": "900001", "attribute": "category", "values": ["cat-x"]}])
        self.assertTrue(any(k == "data" and "jacket, rain" in f for k, f in found))

    def test_not_matching_but_indexed(self):
        _, out, _ = run("--pid", "P88", "--grid", FX / "grid_page1.json", "--match-check", FX / "match_check_empty.json",
                        "--rules-off", FX / "rules_off_empty.json", "--lookup", FX / "lookup_found.json")
        self.assertEqual(out["status"], "not_matching")
        self.assertTrue(any(c["kind"] == "recall" and "in the index but doesn't match" in c["finding"] for c in out["causes"]))

    def test_not_in_index(self):
        _, out, _ = run("--pid", "P66", "--grid", FX / "grid_page1.json", "--match-check", FX / "match_check_empty.json",
                        "--rules-off", FX / "rules_off_empty.json", "--lookup", FX / "lookup_empty.json")
        self.assertEqual(out["status"], "not_in_index")

    def test_not_matching_without_rules_off_or_lookup(self):
        _, out, _ = run("--pid", "P66", "--grid", FX / "grid_page1.json", "--match-check", FX / "match_check_empty.json")
        self.assertEqual(out["status"], "not_matching")
        self.assertTrue(any("--rules-off" in n for n in out["not_checked"]))
        self.assertTrue(any("--lookup" in c["fix"] for c in out["causes"]))

    def test_unknown_without_match_check(self):
        _, out, _ = run("--pid", "P66", "--grid", FX / "grid_page1.json")
        self.assertEqual(out["status"], "unknown")
        self.assertTrue(any("no --match-check" in n for n in out["not_checked"]))

    def test_catalog_text_check_passes_when_words_present(self):
        _, out, _ = run("--pid", "P10", "--grid", FX / "grid_page1.json", "--catalog", FX / "catalog_ok.json",
                        "--query", "wool coat")
        self.assertFalse(any("don't contain" in c["finding"] for c in out["causes"]))

    def test_redirect_and_rewrite(self):
        _, out, _ = run("--pid", "Q01", "--grid", FX / "grid_redirect.json")
        found = kinds(out)
        self.assertTrue(any("redirects" in f for _, f in found))
        self.assertTrue(any("rewritten" in f for _, f in found))
        self.assertEqual(out["rewrites"], {"autoCorrectQuery": "rain jacket"})

    def test_debug_urls_never_output(self):
        _, out, _ = run("--pid", "P10", "--grid", FX / "grid_page1.json")
        self.assertNotIn("FAKEKEY", json.dumps(out))
        self.assertNotIn("feUrl", json.dumps(out))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "result.json"
            _, out, _ = run("--pid", "P10", "--grid", FX / "grid_page1.json", "--out", out_path)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), out)

    def test_errors(self):
        code, out, _ = run("--pid", "P10", "--grid", FX / "error.json")
        self.assertEqual(code, 1)
        self.assertIn("ACCESS_DENIED", out["error"])
        code, out, _ = run("--pid", "P10", "--grid", FX / "missing.json")
        self.assertEqual(code, 1)
        self.assertIn("can't read it", out["error"])
        code, out, _ = run("--pid", " ", "--grid", FX / "grid_page1.json")
        self.assertEqual(code, 1)
        self.assertIn("--pid is empty", out["error"])
        code, _, err = run("--grid", FX / "grid_page1.json")
        self.assertEqual(code, 2)
        self.assertIn("--pid", err)

    def test_account_list_errors_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "err.json"
            path.write_text(json.dumps({"result": {"success": False, "error": "Unknown account_name. Available accounts: "
                                                   "acme_one, acme_two, acme_three, acme_four"}}), encoding="utf-8")
            code, out, _ = run("--pid", "P10", "--grid", path)
            long_err = Path(tmp) / "long.json"
            long_err.write_text(json.dumps({"success": False, "error": "x" * 500}), encoding="utf-8")
            _, out_long, _ = run("--pid", "P10", "--grid", long_err)
        self.assertEqual(code, 1)
        self.assertNotIn("acme_", out["error"])
        self.assertIn("check the account name", out["error"])
        self.assertNotIn("x" * 201, out_long["error"])

    def test_malformed_rows_and_scores_do_not_crash(self):
        grid = json.loads((FX / "grid_page1.json").read_text(encoding="utf-8"))
        data = grid.get("data", grid)
        data["response"]["docs"].insert(0, "not a row")
        for entries in (data.get("debug") or {}).get("explain.structured", {}).values():
            for e in entries:
                if isinstance(e, dict) and "totalNormalizedScore" in e:
                    e["relevance"] = "n/a"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps(grid), encoding="utf-8")
            code, out, err = run("--pid", "P10", "--grid", path)
        self.assertEqual(code, 0, err)
        self.assertTrue(out["ok"])


class QueryFileTest(unittest.TestCase):
    def test_query_file_round_trips_exactly(self):
        q = 'rain jacket $(x) `y` "z" \'w\''
        with tempfile.TemporaryDirectory() as tmp:
            qf = Path(tmp) / "query.txt"
            qf.write_text(q + "\n", encoding="utf-8", newline="")
            code, out, err = run("--pid", "P10", "--grid", FX / "grid_page1.json", "--query-file", qf)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["query"], q)

    def test_query_and_query_file_together_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            qf = Path(tmp) / "query.txt"
            qf.write_text("rain jacket", encoding="utf-8")
            code, out, _ = run("--pid", "P10", "--grid", FX / "grid_page1.json", "--query", "rain jacket", "--query-file", qf)
        self.assertEqual(code, 1)
        self.assertIn("at most one of --query and --query-file", out["error"])


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
