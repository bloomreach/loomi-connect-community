"""Tests for discovery-catalog-config-audit's config_audit.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-catalog-config-audit"
SCRIPT = SKILL / "scripts/config_audit.py"
FX = ROOT / "tests/fixtures/discovery/catalog_config"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def audit(*args):
    r = run(*args)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return json.loads(r.stdout)


def broken():
    return audit("--config", FX / "config_broken.json", "--reserved", FX / "reserved.json",
                 "--products", FX / "products.json", "--catalogs", FX / "catalogs.json", "--today", "2026-11-03")


def found(out):
    return {(f["priority"], f["check"], f["attribute"]) for f in out["findings"]}


class ConfigAuditTest(unittest.TestCase):
    def test_internal_fields(self):
        f = found(broken())
        self.assertIn(("high", "internal field exposed", "unit_margin"), f)
        self.assertIn(("medium", "internal field exposed", "supplier_cost"), f)

    def test_internal_values_never_printed(self):
        r = run("--config", FX / "config_broken.json", "--products", FX / "products.json", "--today", "2026-11-03")
        out = json.loads(r.stdout)
        # Sampled margins are 31, 22 and 40; only names and fill rates are printed.
        for value in ('"31"', ": 31", ": 22", ": 40"):
            self.assertNotIn(value, r.stdout)
        self.assertEqual(next(a for a in out["attributes"] if a["name"] == "unit_margin")["sample_fill"], 1.0)

    def test_searchability(self):
        f = found(broken())
        self.assertIn(("high", "key attribute not searchable", "brand"), f)
        self.assertIn(("medium", "key attribute not searchable", "category_names"), f)
        self.assertIn(("low", "numeric attribute searchable", "price, sale_price"), f)
        self.assertIn(("medium", "numeric attribute searchable", "pack_weight"), f)
        self.assertIn(("low", "identifier searchable", "ean_code"), f)

    def test_duplicates_and_unconfigured(self):
        out = broken()
        f = found(out)
        self.assertIn(("medium", "duplicates a reserved attribute", "product_brand"), f)
        self.assertIn(("low", "unconfigured attribute", "loyalty_points"), f)
        note = next(x for x in out["findings"] if x["check"] == "unconfigured attribute")
        self.assertIn('searchable false', note["issue"])

    def test_variant_index_and_autosuggest(self):
        f = found(broken())
        self.assertIn(("medium", "variant settings", "variants.use_unavailable_variant_as_hero"), f)
        self.assertIn(("low", "variant settings", "fit"), f)
        self.assertIn(("high", "index safety", "index.enable_index_jobs"), f)
        self.assertIn(("medium", "index safety", "index.search_docs_drop_threshold"), f)
        self.assertIn(("low", "autosuggest", "autosuggest.minimum_character_count"), f)
        self.assertIn(("medium", "catalog", "acme_store"), f)

    def test_fill_rates(self):
        f = found(broken())
        self.assertIn(("high", "key attribute missing", "thumb_image"), f)
        self.assertIn(("medium", "key attribute missing", "brand"), f)
        self.assertIn(("medium", "configured but empty", "fit"), f)
        self.assertIn(("low", "configured but empty", "story"), f)
        self.assertNotIn(("medium", "configured but empty", "fabric"), f)  # 2 of 3 filled

    def test_sorted_by_priority_and_counts(self):
        out = broken()
        order = [f["priority"] for f in out["findings"]]
        self.assertEqual(order, sorted(order, key=["high", "medium", "low"].index))
        self.assertEqual(sum(out["counts"].values()), len(out["findings"]))
        self.assertIn("Fill rates are rough: only 3 products sampled (see min_sample).", out["not_checked"])

    def test_clean_config(self):
        out = audit("--config", FX / "config_clean.json", "--reserved", FX / "reserved.json", "--today", "2026-11-03")
        self.assertEqual(out["findings"], [])
        self.assertIn("Fill rates: no --products sample.", out["not_checked"])
        self.assertIn("Index freshness and document counts: no --catalogs file.", out["not_checked"])

    def test_without_reserved_or_catalog_name(self):
        out = audit("--config", FX / "config_clean.json", "--catalogs", FX / "catalogs.json", "--catalog", "nope")
        self.assertTrue(any("--reserved" in n for n in out["not_checked"]))
        self.assertTrue(any("name the catalog" in n for n in out["not_checked"]))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "audit.json"
            out = audit("--config", FX / "config_clean.json", "--today", "2026-11-03", "--out", target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), out)

    def test_errors(self):
        r = run("--config", FX / "denied.json")
        self.assertEqual(r.returncode, 1)
        err = json.loads(r.stdout)["error"]
        self.assertIn("error about the account name", err)
        self.assertNotIn("bravo", err)
        r = run("--config", FX / "missing.json")
        self.assertIn("can't read it as JSON", json.loads(r.stdout)["error"])
        r = run("--config", FX / "reserved.json")
        self.assertIn("custom_attributes is missing", json.loads(r.stdout)["error"])
        r = run("--config", FX / "config_clean.json", "--today", "yesterday")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a date", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_bad_product_and_catalog_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            prods = Path(tmp) / "p.json"
            prods.write_text(json.dumps({"data": [{"id": "1", "attributes": "oops"}]}), encoding="utf-8")
            r = run("--config", FX / "config_clean.json", "--products", prods)
            self.assertIn("has no attributes object", json.loads(r.stdout)["error"])
            cats = Path(tmp) / "c.json"
            cats.write_text(json.dumps({"data": [{"name": "x", "environment": "production",
                                                  "stats": {"last_index_refresh_at": "last week"}}]}), encoding="utf-8")
            r = run("--config", FX / "config_clean.json", "--catalogs", cats)
            self.assertIn("isn't a date", json.loads(r.stdout)["error"])
            self.assertNotIn("Traceback", r.stderr)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
