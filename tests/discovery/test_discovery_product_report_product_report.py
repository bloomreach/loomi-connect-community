"""Tests for discovery-product-report's product_report.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-product-report"
SCRIPT = SKILL / "scripts/product_report.py"
FX = ROOT / "tests/fixtures/discovery/product_report"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def report(*args):
    r = run("--today", "2026-11-03", *args)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return json.loads(r.stdout)


def peers():
    return [x for i in range(1, 5) for x in ("--peer", FX / f"peer{i}.json")]


class ProductReportTest(unittest.TestCase):
    def test_peer_comparison_and_weak_conversion(self):
        out = report("--pid", "p100", "--performance", FX / "perf.json", *peers())
        self.assertEqual(out["peers"], 4)
        conv = out["performance"]["conversion_rate"]
        self.assertEqual((conv["value"], conv["peer_median"], conv["level"]), (2.0, 5.25, "weak"))
        self.assertEqual(out["performance"]["visits"]["level"], "typical")
        self.assertTrue(any(a["hand_off"] == "product-data-enhancer" and a["priority"] == "medium" for a in out["actions"]))

    def test_table_gives_trend_and_category_peers(self):
        out = report("--pid", "p100", "--performance", FX / "perf.json", "--table", FX / "table.json",
                     "--category-grid", f"c10={FX / 'grid_category.json'}", *peers())
        self.assertEqual(out["trend"]["revenue"], {"now": 1500.0, "before": 2100.0})
        # p205 is on the category's page one and in the table; p999 isn't in the category.
        self.assertEqual(out["peers"], 5)

    def test_positions_skip_banners_and_flag_off_page_one(self):
        out = report("--pid", "p100", "--performance", FX / "perf_strong.json", *peers(),
                     "--grid", f"rain jacket={FX / 'grid_rain_jacket.json'}", "--queries", FX / "queries.json")
        g = out["positions"][0]
        self.assertEqual((g["position"], g["on_page_one"], g["query_revenue"]), (30, False, 5000.0))
        self.assertEqual(g["scores"]["relevance"], 21)
        top = out["actions"][0]
        self.assertEqual((top["priority"], top["hand_off"]), ("high", "discovery-product-visibility"))
        self.assertIn("converts well", top["finding"])

    def test_boosted_while_low_on_stock_is_high(self):
        out = report("--pid", "p100", "--performance", FX / "perf.json", "--catalog", FX / "catalog.json",
                     "--grid", f"jacket={FX / 'grid_jacket.json'}")
        g = out["positions"][0]
        self.assertEqual((g["position"], g["rules_applied"]), (2, ["hardBoost"]))
        self.assertEqual(out["rules"], [{"rule_id": 501, "rule_type": "ranking", "effect": "boosted",
                                         "item": "boost_top_products", "audiences": [], "in_test": False,
                                         "where": ["search 'jacket'"]}])
        self.assertEqual(out["actions"][0]["priority"], "high")
        self.assertEqual(out["actions"][0]["hand_off"], "discovery-change-qa")

    def test_bury_pin_and_redirect(self):
        out = report("--pid", "p100", "--performance", FX / "perf_strong.json", *peers(),
                     "--grid", f"coat={FX / 'grid_coat.json'}", "--grid", f"parka={FX / 'grid_parka.json'}",
                     "--grid", f"jackets={FX / 'grid_redirected.json'}")
        effects = {r["rule_id"]: r["effect"] for r in out["rules"]}
        self.assertEqual(effects, {502: "buried", 503: "pinned"})
        bury = next(r for r in out["rules"] if r["rule_id"] == 502)
        self.assertEqual((bury["audiences"], bury["in_test"]), (["Mobile"], True))
        self.assertTrue(any("buries it" in a["finding"] for a in out["actions"]))
        redirected = next(g for g in out["positions"] if g["name"] == "jackets")
        self.assertTrue(redirected["redirect"])
        # A redirected query isn't reported as "off page one".
        self.assertFalse(any("'jackets'" in a["finding"] for a in out["actions"]))

    def test_catalog_variants_and_no_commercial_fields(self):
        out = report("--pid", "p100", "--performance", FX / "perf.json", "--catalog", FX / "catalog.json",
                     "--variants", FX / "variants.json")
        c = out["catalog"]
        self.assertEqual((c["low_stock"], c["missing_fields"], c["category_paths"], c["variant_count"]),
                         (True, ["description"], ["women > jackets"], 3))
        self.assertEqual(out["variants"], {"fetched": 3, "total": 3, "in_stock": 2, "all_out_of_stock": False,
                                           "missing_images": 1})
        text = json.dumps(out)
        self.assertNotIn("margin", text)
        self.assertNotIn('"cost"', text)
        self.assertNotIn("auth_key", text)
        self.assertTrue(any("missing" in a["finding"] for a in out["actions"]))

    def test_all_variants_out_counts_as_out_of_stock(self):
        out = report("--pid", "p100", "--performance", FX / "perf.json", "--catalog", FX / "catalog_ok.json",
                     "--variants", FX / "variants_out.json", "--grid", f"parka={FX / 'grid_parka.json'}")
        self.assertTrue(out["variants"]["all_out_of_stock"])
        self.assertEqual(out["actions"][0]["hand_off"], "discovery-change-qa")

    def test_not_checked_and_action_cap(self):
        out = report("--pid", "p100", "--performance", FX / "perf.json")
        self.assertEqual(len(out["not_checked"]), 5)
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        out = report("--pid", "p100", "--performance", FX / "perf_strong.json", *peers(), "--catalog",
                     FX / "catalog.json", "--variants", FX / "variants.json",
                     "--grid", f"rain jacket={FX / 'grid_rain_jacket.json'}", "--grid", f"jacket={FX / 'grid_jacket.json'}",
                     "--grid", f"coat={FX / 'grid_coat.json'}")
        self.assertLessEqual(len(out["actions"]), rules["max_actions"])
        self.assertEqual([a["priority"] for a in out["actions"]], sorted(
            (a["priority"] for a in out["actions"]), key=["high", "medium", "low"].index))

    def test_out_file_and_page_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            out = report("--pid", "p100", "--performance", FX / "perf.json", "--page-size", "40",
                         "--grid", f"rain jacket={FX / 'grid_rain_jacket.json'}", "--out", path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), out)
        self.assertTrue(out["positions"][0]["on_page_one"])

    def test_errors(self):
        r = run("--pid", "p100", "--performance", FX / "error_accounts.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't repeated", r.stdout)
        self.assertNotIn("acme_a", r.stdout)
        r = run("--pid", "p100", "--performance", FX / "error_plain.json")
        self.assertEqual(r.returncode, 1)
        err = json.loads(r.stdout)["error"]
        self.assertIn("x" * 200, err)
        self.assertNotIn("x" * 201, err)
        for args, needle in [(["--performance", FX / "peer1.json"], "not p100"),
                             (["--performance", FX / "perf.json", "--grid", f"x={FX / 'not_grid.json'}"], "no response.docs"),
                             (["--performance", FX / "perf.json", "--catalog", FX / "catalog_bad.json"], "no attributes"),
                             (["--performance", FX / "perf.json", "--table", FX / "perf.json"], "no rows"),
                             (["--performance", FX / "missing.json"], "can't read it")]:
            r = run("--pid", "p100", *args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(needle, json.loads(r.stdout)["error"])
            self.assertNotIn("Traceback", r.stderr)
        for args in (["--grid", "no-equals-sign"], ["--today", "yesterday"]):
            r = run("--pid", "p100", "--performance", FX / "perf.json", *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("Traceback", r.stderr)

    def test_name_file_splits_on_first_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "grid=1.json"
            odd.write_text((FX / "grid_jacket.json").read_text(encoding="utf-8"), encoding="utf-8")
            out = report("--pid", "p100", "--performance", FX / "perf.json", "--grid", f"jacket={odd}")
        self.assertEqual(out["positions"][0]["name"], "jacket")

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
