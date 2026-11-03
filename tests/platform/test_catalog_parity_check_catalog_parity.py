import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-platform/skills/catalog-parity-check/scripts/catalog_parity.py"
FIX = ROOT / "tests/fixtures/platform/catalog_parity"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8")


def full_run(*extra):
    p = run("--products", FIX / "products.json", "--grid", f"boots={FIX / 'grid_boots.json'}",
            "--discovery", FIX / "discovery_lookup.json", "--discovery-random", FIX / "discovery_random.json",
            "--engagement", FIX / "engagement_lookup.json", "--engagement", FIX / "engagement_not_found.json",
            "--engagement-random", FIX / "engagement_random.json",
            "--not-in-engagement", "P500", "--not-in-discovery", "OLD1,OLD2", *extra)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def finding(out, pid):
    return next(f for f in out["findings"] if f["product_id"] == pid)


class CatalogParityTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_stock_mismatch_ranks_first_by_priority_and_revenue(self):
        out = full_run()
        first = out["findings"][0]
        self.assertEqual(first["product_id"], "P200")
        self.assertEqual(first["checks"][0]["check"], "stock_out_on_site_in_engagement")
        self.assertEqual(first["revenue_at_stake"], 8000.0)

    def test_ids_match_case_insensitively_and_urls_and_images_normalise(self):
        out = full_run()
        # P100 is "p100" in Engagement, with an http URL, a trailing slash and the same image file on another host.
        self.assertNotIn("P100", [f["product_id"] for f in out["findings"]])

    def test_price_title_image_and_stock_in_on_site(self):
        checks = {c["check"]: c for c in finding(full_run(), "P300")["checks"]}
        self.assertEqual(checks["price_mismatch"]["discovery"], 15.0)
        self.assertEqual(checks["price_mismatch"]["engagement"], 18.5)
        self.assertIn("stock_in_on_site_out_in_engagement", checks)
        self.assertIn("image_mismatch", checks)
        self.assertIn("title_mismatch", checks)

    def test_sale_price_only_in_one_catalog(self):
        checks = {c["check"]: c for c in finding(full_run(), "R2")["checks"]}
        self.assertEqual(checks["sale_price_mismatch"]["detail"], "sale price only in engagement")

    def test_missing_both_ways_and_not_found_file(self):
        out = full_run()
        self.assertEqual(finding(out, "R3")["checks"][0]["check"], "missing_in_engagement")  # from the not-found file
        self.assertEqual(finding(out, "P500")["checks"][0]["check"], "missing_in_engagement")
        self.assertEqual(finding(out, "OLD1")["priority"], "high")
        self.assertEqual(finding(out, "OLD2")["priority"], "low")  # already out of stock in Engagement
        self.assertEqual(out["unchecked"], {"not_looked_up_in_engagement": ["P400"]})

    def test_rates_use_the_random_sample_with_an_interval(self):
        rates = full_run()["rates_random_sample"]
        self.assertEqual(rates["missing_in_engagement"]["mismatches"], 1)
        self.assertEqual(rates["missing_in_engagement"]["compared"], 3)
        self.assertEqual(rates["missing_in_engagement"]["rate_pct"], 33.3)
        self.assertNotIn("missing_in_discovery", rates)
        # Discovery random sample only: R1 matches, R2 differs (R3 is missing in Engagement).
        self.assertEqual(rates["price"], {"mismatches": 1, "compared": 2, "rate_pct": 50.0, "interval_pct": [9.5, 90.5]})

    def test_engagement_side_is_reported_separately_as_not_random(self):
        rates = full_run()["rates_engagement_sample"]
        self.assertIn("not a random sample", rates["note"])
        self.assertEqual(rates["missing_in_discovery"]["compared"], 3)
        self.assertEqual(rates["missing_in_discovery"]["mismatches"], 2)
        self.assertEqual(rates["price"]["compared"], 1)  # R1, the only Engagement-side item also on the site

    def test_never_outputs_margin_or_cost(self):
        text = json.dumps(full_run())
        self.assertNotIn("margin", text)
        self.assertNotIn("cost", text)
        self.assertNotIn("0.42", text)

    def test_field_override_refuses_commercial_fields(self):
        p = run("--products", FIX / "products.json", "--field", "price=margin:cost_per_unit")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("never compared or output", p.stderr)

    def test_field_override_and_engagement_key(self):
        out = full_run("--field", "title=pid:title")
        self.assertTrue(any(c["check"] == "title_mismatch" for f in out["findings"] for c in f["checks"]))
        out = full_run("--engagement-key", "no_such_property")
        self.assertIn("not_looked_up_in_engagement", out["unchecked"])

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "parity.json"
            p = run("--discovery", FIX / "discovery_lookup.json", "--engagement", FIX / "engagement_lookup.json",
                    "--out", target)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["ok"])

    def test_error_response_stops(self):
        p = run("--engagement", FIX / "denied.json")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn("ACCESS_DENIED", json.loads(p.stdout)["error"])

    def test_unreadable_file(self):
        p = run("--discovery", FIX / "no_such_file.json")
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)["ok"])

    def test_rules_file_is_complete(self):
        rules = json.loads((SCRIPT.parent.parent / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})


if __name__ == "__main__":
    unittest.main()
