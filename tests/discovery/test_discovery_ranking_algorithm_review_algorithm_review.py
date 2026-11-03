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
        self.assertEqual([f["priority"] for f in cross], ["fix now"])
        self.assertEqual([f["priority"] for f in self.out["findings"]][:2], ["fix now", "fix now"])

    def test_global_cross_type_reported_once(self):
        self.assertEqual(len(find(self.out, "cross-type", "br-margin")), 1)

    def test_status_checks(self):
        self.assertEqual(find(self.out, "error", "br-err")[0]["priority"], "review")  # not in use
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
                             (["--algorithms", FX / "algos_keyword.json", "--query-grid", f"x={FX / 'grid_nodebug.json'}"], "no debug output"),
                             (["--algorithms", FX / "algos_keyword.json", "--query-grid", "nofile"], "NAME=FILE"),
                             (["--algorithms", FX / "algos_keyword.json", "--today", "03/11/2026"], "YYYY-MM-DD")]:
            r = run(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(needle, json.loads(r.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
