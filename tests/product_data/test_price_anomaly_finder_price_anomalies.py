import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-product-data/skills/price-anomaly-finder"
SCRIPT = SKILL / "scripts/price_anomalies.py"
FIX = ROOT / "tests/fixtures/product_data/price-anomaly-finder"


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd or tmp,
                              capture_output=True, text=True, encoding="utf-8")


def mugs(*extra):
    p = run(FIX / "grid_mugs.json", FIX / "grid_mugs_p2.json", "--performance", FIX / "performance.json",
            "--rank", f"mug={FIX / 'rank_mug.json'}", *extra)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout)


def by(out, check):
    return {f["pid"]: f for f in out["findings"] if f["check"] == check}


class PriceAnomaliesTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertTrue(rules["about"])
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys - set(rules["notes"]), set())
        self.assertEqual(set(rules["notes"]) - keys, set())

    def test_times_100_unit_error(self):
        f = by(mugs(), "unit_error")["MUG-X100"]
        self.assertEqual(f["priority"], "high")  # it earns revenue
        self.assertIn("÷100 gives 15.99", f["issue"])
        self.assertEqual(f["owner"], "feed team")

    def test_outlier_that_is_not_a_unit_error(self):
        out = mugs()
        self.assertIn("MUG-OUT", by(out, "category_outlier"))
        self.assertNotIn("MUG-OUT", by(out, "unit_error"))
        # ordinary prices are never outliers
        flagged = {f["pid"] for f in out["findings"] if f["check"] in ("category_outlier", "unit_error")}
        self.assertEqual(flagged, {"MUG-OUT", "MUG-X100"})

    def test_robust_median_not_mean(self):
        out = mugs()
        g = out["groups"][0]
        self.assertEqual((g["group"], g["median"]), ("Mugs", "16.50"))  # 'Mugs|Drinkware' groups under Mugs

    def test_sale_above_price(self):
        out = mugs()
        f = by(out, "sale_not_below_price")
        self.assertIn("Sale price 19.50 is above the regular price 16.00", f["MUG-SALEUP"]["issue"])
        self.assertIn("Variant MUG-VAR-3", f["MUG-VAR"]["issue"])

    def test_sale_equal_price_reported_when_not_default(self):
        p = run(FIX / "engagement_items.json")
        out = json.loads(p.stdout)
        f = by(out, "sale_not_below_price")
        self.assertEqual(f["ENG-1"]["priority"], "low")
        self.assertIn("equals", f["ENG-1"]["issue"])
        self.assertIn("above", f["ENG-2"]["issue"])  # Engagement: price above original_price
        self.assertNotIn("ENG-3", f)

    def test_sale_equal_price_default_collapses(self):
        out = json.loads(run(f"Lamps={FIX / 'grid_default_sale.json'}").stdout)
        self.assertEqual(out["findings"], [])
        self.assertIn("10 of 10 priced products", out["catalog_notes"][0])

    def test_deep_discount_zero_missing(self):
        out = mugs()
        self.assertIn("90% below", by(out, "discount_too_deep")["MUG-DEEP"]["issue"])
        missing = [f for f in out["findings"] if f["check"] == "price_missing"]
        self.assertEqual({f["pid"]: f["priority"] for f in missing}, {"MUG-ZERO": "high", "MUG-NONE": "low"})

    def test_variant_spread_names_unit_error(self):
        f = by(mugs(), "variant_price_spread")["MUG-VAR"]
        self.assertIn("about ×100", f["issue"])
        self.assertIn("MUG-VAR-3", f["issue"])

    def test_duplicate_ids_and_titles(self):
        out = mugs()
        f = [x for x in out["findings"] if x["check"] == "duplicate_price_conflict"]
        self.assertIn("Product ID MUG-03 appears more than once, at 15.00 and 30.00", [x["issue"] for x in f])
        self.assertEqual({x["pid"] for x in f}, {"MUG-03", "MUG-DUP-A", "MUG-DUP-B"})

    def test_never_outputs_margin_or_cost(self):
        p = run(FIX / "grid_mugs.json")
        self.assertNotIn("margin", p.stdout)
        self.assertNotIn("4.50", p.stdout)
        self.assertNotIn("7.25", p.stdout)

    def test_deterministic(self):
        self.assertEqual(mugs(), mugs())

    def test_csv_escapes_formulas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "findings.csv"
            run(FIX / "grid_mugs.json", "--csv", path)
            with open(path, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        row = next(r for r in rows if "HYPERLINK" in r["pid"])
        self.assertEqual(row["pid"], "'=HYPERLINK(1)")
        self.assertEqual(row["title"], "'-Example formula mug")

    def test_group_is_the_breadcrumb_leaf(self):
        spec = importlib.util.spec_from_file_location("price_anomalies", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.group_of("Home > Kitchen > Knives"), "Knives")
        self.assertEqual(mod.group_of("Women > Dresses|Women > Sale"), "Dresses")
        self.assertEqual(mod.group_of("Tops/T-Shirts"), "T-Shirts")
        self.assertEqual(mod.group_of("Mugs|Drinkware"), "Mugs")
        self.assertEqual(mod.group_of(["Lamps"]), "Lamps")

    def test_error_response_hides_account_names(self):
        p = run(FIX / "denied.json")
        self.assertEqual(p.returncode, 1)
        out = json.loads(p.stdout)
        self.assertFalse(out["ok"])
        self.assertNotIn("alpha", out["error"])


if __name__ == "__main__":
    unittest.main()
