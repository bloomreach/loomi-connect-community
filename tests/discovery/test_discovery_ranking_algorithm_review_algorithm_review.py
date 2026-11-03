"""Tests for discovery-ranking-algorithm-review's algorithm_review.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-ranking-algorithm-review"
SCRIPT = SKILL / "scripts/algorithm_review.py"
FX = ROOT / "tests/fixtures/discovery/algorithm_review"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def full(*extra):
    details = [a for n in (2, 3, 5, 6, 12, 13, 14) for a in ("--detail", FX / f"detail_{n}.json")]
    grids = [a for q in ("dress", "shirt", "jeans", "ghost") for a in ("--query-grid", f"{q}={FX / f'grid_q_{q}.json'}")]
    grids += [a for c in ("100", "200", "300", "400") for a in ("--category-grid", f"{c}={FX / f'grid_c_{c}.json'}")]
    r = run("--algorithms", FX / "algos_keyword.json", "--algorithms", FX / "algos_category.json", *details, *grids,
            "--queries", FX / "queries_perf.json", "--categories", FX / "categories_perf.json", "--today", "2026-11-03", *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout), r.stdout


def find(out, check, algorithm_part=""):
    return [f for f in out["findings"] if f["check"] == check and algorithm_part in f["algorithm"]]


class AlgorithmReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.text = full()

    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_never_prints_editors_or_keys(self):
        self.assertNotIn("example.test", self.text)
        self.assertNotIn("FAKEKEY123", self.text)

    def test_effective_algorithm_per_scope(self):
        scopes = {(s["kind"], s["scope"]): s for s in self.out["scopes"]}
        self.assertEqual(scopes[("KEYWORD", "dress")]["algorithm"], "Text relevance (br-text, KEYWORD)")  # query rule beats global
        self.assertEqual(scopes[("KEYWORD", "shirt")]["algorithm"], "Margin (br-margin, KEYWORD)")  # global rule
        self.assertEqual(scopes[("KEYWORD", "jeans")]["algorithm"], "Classic search ranking (br-standard, KEYWORD)")  # default
        # br-standard is both a KEYWORD and a CATEGORY algorithm: the category scope gets the CATEGORY one.
        self.assertEqual(scopes[("CATEGORY", "100")]["algorithm"], "Classic category ranking (br-standard, CATEGORY)")
        self.assertEqual(scopes[("CATEGORY", "300")]["via_rule"], 952)

    def test_audience_rules_are_seen_but_not_effective(self):
        margin = next(a for a in self.out["algorithms"] if a["algoId"] == "br-margin")
        vip = [u for u in margin["used_on"] if u["audiences"]]
        self.assertEqual(len(vip), 1)
        self.assertFalse(vip[0]["effective"])

    def test_fix_now(self):
        self.assertEqual(len(find(self.out, "missing algorithm", "br-deleted")), 1)
        cross = find(self.out, "cross-type", "br-text")
        self.assertEqual([f["priority"] for f in cross], ["high"])
        self.assertEqual([f["priority"] for f in self.out["findings"]][:2], ["high", "high"])
        self.assertEqual(set(self.out["summary"]["findings"]), {"high", "medium", "low"})

    def test_global_cross_type_reported_once(self):
        self.assertEqual(len(find(self.out, "cross-type", "br-margin")), 1)

    def test_status_checks(self):
        self.assertEqual(find(self.out, "error", "br-err")[0]["priority"], "medium")  # not in use
        self.assertEqual(len(find(self.out, "stuck training", "br-train")), 1)
        self.assertEqual(len(find(self.out, "stuck sync", "br-sync")), 1)
        self.assertEqual(len(find(self.out, "stale", "br-text")), 1)

    def test_weight_checks(self):
        self.assertIn("98%", find(self.out, "dominant signal", "br-noperf")[0]["detail"])
        self.assertEqual(len(find(self.out, "ignores shoppers", "br-noperf")), 1)
        self.assertEqual(len(find(self.out, "revenue at zero", "br-norev")), 1)
        self.assertEqual(len(find(self.out, "custom signal", "br-margin")), 1)
        self.assertIn("unigram_color_tf", find(self.out, "flat signals", "br-cat")[0]["detail"])
        abr = next(a for a in self.out["algorithms"] if a["algoId"] == "br-train")
        self.assertEqual(abr["weights"]["top"][0], {"signal": "text_match", "share": 0.6})  # ABR weights list

    def test_duplicates_and_unused(self):
        self.assertEqual(len(find(self.out, "near-duplicate", "br-copy")), 1)
        self.assertEqual(len(find(self.out, "same name")), 1)
        unused = {f["algorithm"] for f in find(self.out, "not seen in use")}
        self.assertIn("Category optimised (br-cat, CATEGORY)", unused)
        self.assertNotIn("Classic search ranking (br-standard, KEYWORD)", unused)  # the default

    def test_conversion_comparison(self):
        lead = find(self.out, "converts less", "br-margin")
        self.assertEqual(len(lead), 1)
        self.assertIn("1.0% against 4.0%", lead[0]["detail"])
        self.assertEqual(find(self.out, "converts less", "br-noperf"), [])  # under min_visits

    def test_not_checked(self):
        nc = " ".join(self.out["not_checked"])
        self.assertIn("category '400'", nc)
        self.assertNotIn("'ghost'", nc)  # its rule points at a missing algorithm: that's a finding
        self.assertIn("No CATEGORY algorithm is marked Default", nc)
        self.assertEqual(self.out["defaults"]["KEYWORD"], ["Classic search ranking (br-standard, KEYWORD)"])

    def test_without_grids(self):
        r = run("--algorithms", FX / "algos_keyword.json", "--today", "2026-11-03")
        out = json.loads(r.stdout)
        self.assertTrue(any("no product grids" in n for n in out["not_checked"]))
        self.assertEqual(find(out, "not seen in use"), [])

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            out, _ = full("--out", path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), out)

    def test_errors(self):
        for args, needle in [(["--algorithms", FX / "denied.json"], "ACCESS_DENIED"),
                             (["--algorithms", FX / "missing.json"], "can't read JSON"),
                             (["--algorithms", FX / "queries_perf.json"], "No algorithms"),
                             (["--algorithms", FX / "algos_keyword.json", "--detail", FX / "queries_perf.json"], "not a search_ranking_algorithms detail"),
                             (["--algorithms", FX / "algos_keyword.json", "--query-grid", f"x={FX / 'grid_nodebug.json'}"], "no debug output")]:
            r = run(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(needle, json.loads(r.stdout)["error"])
        # Bad arguments are argparse errors: exit 2, one line on stderr, no traceback.
        for args, needle in [(["--query-grid", "nofile"], "NAME=FILE"), (["--query-grid", "=x.json"], "NAME=FILE"),
                             (["--today", "03/11/2026"], "YYYY-MM-DD")]:
            r = run("--algorithms", FX / "algos_keyword.json", *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn(needle, r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_name_file_splits_on_the_first_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "a=b"
            odd.mkdir()
            grid = odd / "grid.json"
            grid.write_text((FX / "grid_q_dress.json").read_text(encoding="utf-8"), encoding="utf-8")
            r = run("--algorithms", FX / "algos_keyword.json", "--query-grid", f"dress={grid}", "--today", "2026-11-03")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["scopes"][0]["scope"], "dress")

    def test_account_list_errors_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "denied.json"
            bad.write_text(json.dumps({"success": False, "error": "Unknown account 'acme'. Accounts you can access: "
                                       "alpha_store, beta_shop, gamma_retail, delta_outlet"}), encoding="utf-8")
            r = run("--algorithms", bad)
            long = Path(tmp) / "long.json"
            long.write_text(json.dumps({"success": False, "error": "x" * 500}), encoding="utf-8")
            r2 = run("--algorithms", long)
        self.assertEqual(r.returncode, 1)
        error = json.loads(r.stdout)["error"]
        self.assertIn("check the account name", error)
        self.assertNotIn("beta_shop", error)
        self.assertLess(len(json.loads(r2.stdout)["error"]), 400)

    def test_malformed_dates_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "algos.json"
            bad.write_text(json.dumps({"data": [{"id": 1, "algoId": "br-x", "searchType": "KEYWORD",
                                                 "lastModifiedAt": "yesterday"}]}), encoding="utf-8")
            r = run("--algorithms", bad, "--today", "2026-11-03")
        self.assertEqual(r.returncode, 1)
        self.assertIn("lastModifiedAt", json.loads(r.stdout)["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_number_parser(self):
        import importlib.util
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("algorithm_review", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.number("(12.00)"), -12.0)
        self.assertEqual(mod.number("1.5e3"), 1500.0)
        self.assertEqual(mod.number("$1,234.50"), 1234.5)
        self.assertEqual(mod.number("10.00%"), 10.0)
        self.assertIsNone(mod.number("n/a"))
        self.assertIsNone(mod.number(True))


if __name__ == "__main__":
    unittest.main()
