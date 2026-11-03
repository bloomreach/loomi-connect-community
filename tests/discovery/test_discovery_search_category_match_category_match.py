"""Tests for discovery-search-category-match's category_match.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-search-category-match"
SCRIPT = SKILL / "scripts/category_match.py"
FX = ROOT / "tests/fixtures/discovery/search_category_match"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = None  # --help prints text
    return r.returncode, out, r.stderr


def find(*extra):
    code, out, err = run("find", "--queries", FX / "queries.json", "--categories", FX / "categories.json", *extra)
    assert code == 0, err
    return out


def pair(query, cat_id, search, category):
    return ["--pair", f"{query}|{cat_id}|{FX / search}|{FX / category}"]


def compare(*pairs, perf=True):
    args = ["compare"] + [x for p in pairs for x in p] + ["--categories", FX / "categories.json"]
    if perf:
        args += ["--queries", FX / "queries.json", "--category-perf", FX / "category_perf.json"]
    code, out, err = run(*args)
    assert code == 0, err
    return {p["query"]: p for p in out["pairs"]}, out


class FindTest(unittest.TestCase):
    def test_matches_by_name_department_and_synonym(self):
        out = find("--synonyms", FX / "synonyms.json")
        got = {p["query"]: ([c["path"] for c in p["categories"]], p["status"]) for p in out["pairs"]}
        self.assertEqual(got["dress"], (["/women/dresses"], "single"))  # plural category name
        self.assertEqual(got["skirt"], (["/women/skirts"], "single"))
        self.assertEqual(got["mens pants"], (["/men/pants"], "single"))  # department word picks one
        self.assertEqual(got["womens shoes"], (["/women/shoes"], "single"))
        self.assertEqual(got["pants"], (["/men/pants", "/women/pants"], "ambiguous"))
        self.assertEqual(got["tops"][1], "ambiguous")
        self.assertEqual(len(got["tops"][0]), 3)
        self.assertEqual(got["trouser"], (["/men/pants", "/women/pants"], "ambiguous"))
        self.assertEqual(got["summer sale"], (["/summer sale"], "single"))  # dynamic category
        trouser = next(p for p in out["pairs"] if p["query"] == "trouser")
        self.assertEqual(trouser["categories"][0]["via"], "synonym 'pants'")
        for q in ("black dress", "rain jacket", "quiet thing"):
            self.assertNotIn(q, got)
        self.assertEqual(out["skipped_low_traffic"], 1)
        self.assertEqual(out["ambiguous"], 3)

    def test_without_synonyms_and_disabled_synonyms(self):
        got = {p["query"] for p in find()["pairs"]}
        self.assertNotIn("trouser", got)
        self.assertNotIn("jumper", got)

    def test_group_synonym_works_both_ways(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "q.json"
            q.write_text(json.dumps({"data": {"rows": [{"query": "parka", "browse_sessions": 900}]}}), encoding="utf-8")
            code, out, err = run("find", "--queries", q, "--categories", FX / "categories.json", "--synonyms", FX / "synonyms.json")
        self.assertEqual(code, 0, err)
        self.assertEqual([c["path"] for c in out["pairs"][0]["categories"]], ["/outerwear/jackets"])

    def test_top_and_min_sessions(self):
        out = find("--top", "2")
        self.assertEqual(out["checked"], 2)
        self.assertEqual([p["query"] for p in out["pairs"]], ["mens pants", "skirt"])
        out = find("--min-sessions", "7500")
        self.assertEqual([p["query"] for p in out["pairs"]], ["mens pants", "skirt"])

    def test_grid_id_keeps_original_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "q.json"
            q.write_text(json.dumps({"data": {"rows": [{"query": "lip liners", "browse_sessions": 900}]}}), encoding="utf-8")
            code, out, err = run("find", "--queries", q, "--categories", FX / "categories.json")
        self.assertEqual(out["pairs"][0]["categories"][0]["grid_id"], "1002A0")  # list_categories lower-cases categoryId


class CompareTest(unittest.TestCase):
    def test_verdicts(self):
        got, out = compare(pair("dress", "21200", "search_dress.json", "cat_dresses.json"),
                           pair("skirt", "21000", "search_skirt.json", "cat_skirts.json"),
                           pair("jackets", "40100", "search_jackets.json", "cat_jackets.json"),
                           pair("tops", "10100", "search_tops.json", "cat_men_tops.json"),
                           pair("summer sale", "brg_dyn_summer01", "search_summer.json", "cat_summer.json"),
                           pair("womens shoes", "99999", "search_shoes.json", "cat_shoes_noperf.json"),
                           pair("black dress", "21200", "search_dress.json", "cat_empty.json"))
        self.assertEqual({q: p["verdict"] for q, p in got.items()}, {
            "dress": "aligned", "skirt": "redirect", "jackets": "align_ranking", "tops": "leave",
            "summer sale": "already_redirected", "womens shoes": "review", "black dress": "review"})
        self.assertEqual([p["verdict"] for p in out["pairs"]][:2], ["redirect", "align_ranking"])  # most actionable first
        self.assertEqual(out["counts"]["review"], 2)
        self.assertEqual(got["dress"]["overlap"], 0.83)
        self.assertEqual(got["skirt"]["path"], "/women/skirts")
        self.assertIn("empty", got["black dress"]["why"])
        self.assertIsNone(got["black dress"]["brand_difference"])
        self.assertEqual(got["black dress"]["flags"], [])
        self.assertIn("no performance data", got["womens shoes"]["why"])
        self.assertTrue(any("dynamic" in f for f in got["summer sale"]["flags"]))

    def test_flags_and_banner_rows(self):
        got, _ = compare(pair("skirt", "21000", "search_skirt.json", "cat_skirts.json"))
        s = got["skirt"]
        self.assertEqual(s["search"]["page"], 24)  # the banner row isn't a product
        self.assertEqual(s["search"]["in_stock_share"], 0.17)
        flags = " ".join(s["flags"])
        for needle in ("brand mix differs", "median price differs 3.0x", "fewer in-stock products"):
            self.assertIn(needle, flags)
        self.assertEqual(s["not_checked"], [])
        self.assertNotIn("auth_key", json.dumps(s))

    def test_without_performance_data(self):
        got, _ = compare(pair("skirt", "21000", "search_skirt.json", "cat_skirts.json"), perf=False)
        self.assertEqual(got["skirt"]["verdict"], "review")
        self.assertEqual(len(got["skirt"]["not_checked"]), 2)

    def test_page_size_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "c.json"
            code, out, err = run("compare", *pair("dress", "21200", "search_dress.json", "cat_dresses.json"),
                                 "--page-size", "10", "--out", out_path)
            self.assertEqual(code, 0, err)
            self.assertEqual(out["pairs"][0]["overlap"], 1.0)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), out)


class ErrorTest(unittest.TestCase):
    def test_errors(self):
        code, out, _ = run("find", "--queries", FX / "denied.json", "--categories", FX / "categories.json")
        self.assertEqual(code, 1)
        self.assertIn("ACCESS_DENIED", out["error"])
        code, out, _ = run("find", "--queries", FX / "missing.json", "--categories", FX / "categories.json")
        self.assertEqual(code, 1)
        self.assertIn("can't read it", out["error"])
        code, _, err = run("compare", "--pair", "dress|21200|only-three")
        self.assertEqual(code, 2)
        self.assertIn("four parts", err)
        self.assertNotIn("Traceback", err)

    def test_account_list_errors_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"success": False, "error": "Unknown account 'acme'. Valid accounts: alpha, beta, "
                                       "gamma, delta, epsilon"}), encoding="utf-8")
            code, out, _ = run("find", "--queries", bad, "--categories", FX / "categories.json")
            self.assertEqual(code, 1)
            self.assertIn("isn't repeated", out["error"])
            for name in ("alpha", "beta", "gamma"):
                self.assertNotIn(name, out["error"])
            long = Path(tmp) / "long.json"
            long.write_text(json.dumps({"success": False, "error": "x" * 500}), encoding="utf-8")
            _, out, _ = run("find", "--queries", long, "--categories", FX / "categories.json")
            self.assertLess(len(out["error"]), 400)

    def test_bad_input_never_gives_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            junk = {"list_of_numbers.json": [1, 2, 3], "string.json": "oops", "number.json": 7,
                    "wrong_docs.json": {"data": {"response": {"docs": "x", "numFound": "lots"}}},
                    "wrong_data.json": {"data": "x"}, "not_json.json": None}
            for name, body in junk.items():
                path = Path(tmp) / name
                path.write_text("{not json" if body is None else json.dumps(body), encoding="utf-8")
                runs = [("find", "--queries", path, "--categories", FX / "categories.json"),
                        ("find", "--queries", FX / "queries.json", "--categories", path),
                        ("find", "--queries", FX / "queries.json", "--categories", FX / "categories.json",
                         "--synonyms", path),
                        ("compare", "--pair", f"dress|21200|{path}|{FX / 'cat_dresses.json'}"),
                        ("compare", "--pair", f"dress|21200|{FX / 'search_dress.json'}|{FX / 'cat_dresses.json'}",
                         "--queries", path, "--category-perf", path, "--categories", path)]
                for args in runs:
                    code, out, err = run(*args)
                    self.assertNotIn("Traceback", err, (name, args[0]))
                    self.assertIn(code, (0, 1), (name, args))
            for args in (("find", "--queries", FX / "queries.json", "--categories", FX / "categories.json", "--top", "0"),
                         ("compare", "--pair", f"a|b|{FX / 'search_dress.json'}|{FX / 'cat_dresses.json'}",
                          "--page-size", "x")):
                code, _, err = run(*args)
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", err)

    def test_help(self):
        code, _, _ = run("--help")
        self.assertEqual(code, 0)


class NumberTest(unittest.TestCase):
    def test_number_parsing(self):
        import importlib.util
        sys.dont_write_bytecode = True  # no __pycache__ in the skill folder
        spec = importlib.util.spec_from_file_location("category_match", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for text, want in [("(12.00)", -12.0), ("1.5e3", 1500.0), ("$1,000.00", 1000.0), ("21.43%", 21.43),
                           ("-3", -3.0), ("NA", None), ("", None), (None, None), ("abc", None), (True, None), (7, 7.0)]:
            self.assertEqual(mod.number(text), want, text)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
