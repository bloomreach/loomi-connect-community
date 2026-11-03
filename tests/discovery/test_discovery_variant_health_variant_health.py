"""Tests for discovery-variant-health's variant_health.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-variant-health"
SCRIPT = SKILL / "scripts/variant_health.py"
FX = ROOT / "tests/fixtures/discovery/variant_health"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def full():
    args = ["--grid", f"rain jacket={FX / 'grid_rain.json'}", "--grid", f"category:30100={FX / 'grid_category.json'}",
            "--products", FX / "performance.json", "--catalog", FX / "catalog.json", "--queries", FX / "queries.json"]
    for pid in ("P1", "P3", "P4", "P6", "P7"):
        args += ["--variants", f"{pid}={FX / f'variants_{pid}.json'}"]
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def checks(out, pid):
    return {(f["priority"], f["check"]) for f in out["findings"] if f["pid"] == pid}


class VariantHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = full()

    def test_products_checked(self):
        # 25 products on page one (P5 is 25th product, after a banner row, so it isn't), plus top seller P4 and P8.
        self.assertEqual(self.out["on_page_one"], 25)
        self.assertEqual(self.out["top_sellers"], 4)
        self.assertEqual(self.out["products_checked"], 27)
        self.assertNotIn("P5", {f["pid"] for f in self.out["findings"]})

    def test_out_of_stock(self):
        self.assertIn(("high", "out_of_stock"), checks(self.out, "P1"))
        p1 = next(f for f in self.out["findings"] if f["pid"] == "P1")
        self.assertEqual(p1["page_one"], [{"where": "rain jacket", "position": 1, "query_revenue": 12000.0}])
        self.assertEqual(p1["revenue"], 5000.0)
        self.assertIn("every variant", p1["issue"])
        # A top seller that isn't on page one is medium; its product record says out of stock.
        self.assertIn(("medium", "out_of_stock"), checks(self.out, "P8"))
        # "unknown" stock is neither in nor out.
        self.assertNotIn(("medium", "out_of_stock"), checks(self.out, "P4"))

    def test_prices(self):
        self.assertIn(("high", "price_missing"), checks(self.out, "P2"))  # banner row didn't shift P2's position
        p3 = checks(self.out, "P3")
        for expected in [("high", "price_missing"), ("medium", "sale_above_price"), ("medium", "price_outside_variants")]:
            self.assertIn(expected, p3)

    def test_images_skus_colours(self):
        p3 = checks(self.out, "P3")
        self.assertIn(("medium", "missing_swatch"), p3)
        self.assertIn(("medium", "bad_image_url"), p3)
        self.assertIn(("medium", "duplicate_sku"), checks(self.out, "P3, P6"))
        p4 = checks(self.out, "P4")
        for expected in [("low", "duplicate_sku"), ("low", "missing_thumbnail"), ("low", "single_variant_colour")]:
            self.assertIn(expected, p4)
        self.assertEqual(checks(self.out, "P7"), set())  # clean product

    def test_ordering_and_stake(self):
        order = [f["priority"] for f in self.out["findings"]]
        self.assertEqual(order, sorted(order, key=("high", "medium", "low").index))
        self.assertEqual(self.out["revenue_at_stake"]["high"], 5900.0)  # P1 5000 + P3 900, each counted once

    def test_not_checked(self):
        notes = " ".join(self.out["not_checked"])
        self.assertIn("P4: 6 of 7 variants fetched", notes)
        self.assertIn("Stock not checked for 21 product(s)", notes)

    def test_never_outputs_margin(self):
        self.assertNotIn("margin", json.dumps(self.out))

    def test_grid_only_and_placeholder_images(self):
        r = run("--grid", f"rain jacket={FX / 'grid_rain.json'}", "--catalog", FX / "catalog_no_stock.json",
                "--variants", f"P7={FX / 'variants_placeholder.json'}")
        out = json.loads(r.stdout)
        bad = [f for f in out["findings"] if f["pid"] == "P7" and f["check"] == "bad_image_url"]
        self.assertEqual(len(bad), 2)
        self.assertTrue(any("placeholder host" in f["issue"] for f in bad))
        self.assertTrue(any("placeholder (placeholder)" in f["issue"] for f in bad))
        self.assertTrue(any(n.startswith("Stock: no stock field") for n in out["not_checked"]))
        r = run("--grid", f"rain jacket={FX / 'grid_rain.json'}")
        self.assertTrue(any("no --variants files" in n for n in json.loads(r.stdout)["not_checked"]))

    def test_missing_thumbnail_on_page_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            grid = Path(tmp) / "g.json"
            grid.write_text(json.dumps({"data": {"response": {"docs": [
                {"pid": "X1", "title": "No image", "price": 10, "sale_price": 10, "thumb_image": "", "variants": []}]}}}),
                encoding="utf-8")
            out = json.loads(run("--grid", f"q={grid}").stdout)
        self.assertIn(("high", "missing_thumbnail"), checks(out, "X1"))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.json"
            r = run("--grid", f"rain jacket={FX / 'grid_rain.json'}", "--out", target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), json.loads(r.stdout))

    def test_errors(self):
        r = run("--products", FX / "denied.json")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertIn("isn't repeated because it can list other accounts", out["error"])
        self.assertNotIn("gamma", out["error"])
        for args, text in [(("--grid", f"q={FX / 'not_grid.json'}"), "no response.docs"),
                           (("--grid", f"q={FX / 'missing.json'}"), "can't read it"),
                           (("--grid", f"q={FX / 'grid_rain.json'}", "--variants", f"P1={FX / 'bad_variant.json'}"),
                            "isn't an object"),
                           (("--grid", f"q={FX / 'grid_rain.json'}", "--catalog", FX / "queries.json"),
                            "attributes object"),
                           ((), "at least one")]:
            r = run(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(text, json.loads(r.stdout)["error"])
        r = run("--grid", "no-equals-sign")
        self.assertEqual(r.returncode, 2)
        self.assertIn("NAME=FILE", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_name_file_splits_on_first_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "a=b.json"
            odd.write_text((FX / "grid_category.json").read_text(encoding="utf-8"), encoding="utf-8")
            r = run("--grid", f"q={odd}")
        self.assertEqual(r.returncode, 0, r.stdout)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
