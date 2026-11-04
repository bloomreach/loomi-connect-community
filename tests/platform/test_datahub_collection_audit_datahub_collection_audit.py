"""Tests for datahub-collection-audit's datahub_collection_audit.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-platform/skills/datahub-collection-audit"
SCRIPT = SKILL / "scripts/datahub_collection_audit.py"
FX = ROOT / "tests/fixtures/platform/datahub_collection_audit"


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


FULL = ("--collections", FX / "collections.json",
        "--config", f"products_prod={FX / 'config_prod.json'}",
        "--config", f"products_staging={FX / 'config_staging.json'}",
        "--records", f"products_prod={FX / 'records_prod.json'}",
        "--records", f"products_prod:store={FX / 'records_store.json'}",
        "--fields", f"products_prod={FX / 'fields_prod.json'}",
        "--system", f"products_prod={FX / 'system.json'}",
        "--jobs", FX / "jobs.json", "--catalogs", FX / "catalogs.json", "--today", "2026-11-04")


def found(out):
    return {(f["priority"], f["check"], f["collection"], f["subject"]) for f in out["findings"]}


class DatahubCollectionAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = audit(*FULL)
        cls.f = found(cls.out)

    def test_required_and_key_fields(self):
        self.assertIn(("high", "required field missing", "products_prod", "sku"), self.f)
        self.assertIn(("high", "required field missing", "products_prod", "material"), self.f)
        self.assertIn(("medium", "key field sparse", "products_prod", "title"), self.f)
        # brand is in the system model but neither configured nor sent: not reported.
        self.assertFalse(any(x[1] == "key field sparse" and x[3] == "brand" for x in self.f))

    def test_type_mismatch_counts_not_values(self):
        self.assertIn(("medium", "type mismatch", "products_prod", "price"), self.f)
        self.assertIn(("medium", "type mismatch", "products_prod", "in_stock"), self.f)
        r = run(*FULL)
        for value in ("19.99", "Blue mug", "ceramic", "SKU-1", "yes"):
            self.assertNotIn(value, r.stdout)

    def test_unused_unconfigured_and_dropped(self):
        self.assertIn(("low", "unused field", "products_prod", "colour, geo"), self.f)
        self.assertIn(("low", "unconfigured field", "products_prod", "loyalty_points"), self.f)
        self.assertIn(("high", "field stopped arriving", "products_prod", "material"), self.f)
        self.assertIn(("medium", "field stopped arriving", "products_prod", "colour"), self.f)
        # Built-in system fields are never "unconfigured".
        note = next(x for x in self.out["findings"] if x["check"] == "unconfigured field")
        self.assertNotIn("title", note["subject"])

    def test_drift_between_auto_paired_collections(self):
        self.assertEqual(self.out["pairs_compared"][0]["base"], "products_prod")
        self.assertIn(("high", "configuration drift", "products_prod", "products_prod vs products_staging"), self.f)
        issues = [x["issue"] for x in self.out["findings"] if x["check"] == "configuration drift"]
        self.assertTrue(any("promo_flag" in i for i in issues))
        self.assertTrue(any("different data type: price" in i for i in issues))
        self.assertTrue(any("other settings differ: colour" in i for i in issues))

    def test_jobs(self):
        self.assertIn(("high", "job failing", "products_prod", "items-update"), self.f)
        self.assertIn(("medium", "job failing", "products_staging", "configuration-update"), self.f)
        self.assertIn(("low", "job failed earlier", "products_staging", "records-update"), self.f)
        self.assertIn(("medium", "no recent records", "products_prod", "data jobs"), self.f)
        self.assertIn(("low", "no recent records", "legacy_feed", "data jobs"), self.f)
        row = next(r for r in self.out["collections"] if r["collection"] == "products_prod")
        self.assertEqual(row["latest_successful_data_job"], "2026-10-01")

    def test_item_types_and_catalogs(self):
        self.assertIn(("medium", "collection without item types", "legacy_feed", "legacy_feed"), self.f)
        self.assertIn(("medium", "no records", "products_prod", "store"), self.f)
        self.assertIn(("low", "item type feeds nothing", "products_prod", "store"), self.f)
        self.assertIn(("medium", "catalog without collection", "old_products", "Gift cards"), self.f)
        self.assertIn(("medium", "item type without collection", "products_prod", "Stores"), self.f)
        self.assertIn(("low", "collection unused downstream", "products_staging", "products_staging"), self.f)

    def test_sorted_and_counted(self):
        order = [("high", "medium", "low").index(x["priority"]) for x in self.out["findings"]]
        self.assertEqual(order, sorted(order))
        self.assertEqual(sum(self.out["counts"].values()), len(self.out["findings"]))
        self.assertTrue(any("only 3 records sampled" in n for n in self.out["not_checked"]))
        self.assertTrue(any("GeoPoint" in n for n in self.out["not_checked"]))
        self.assertEqual(audit(*FULL), self.out)

    def test_compare_tool_and_explicit_pairs(self):
        out = audit("--collections", FX / "collections.json", "--no-auto-pair",
                    "--compare", f"products_prod,products_staging={FX / 'compare.json'}", "--today", "2026-11-04")
        drift = [x for x in out["findings"] if x["check"] == "configuration drift"]
        self.assertEqual({x["priority"] for x in drift}, {"high", "medium"})
        self.assertEqual(out["pairs_compared"], [{"base": "products_prod", "reference": "products_staging",
                                                  "source": "compare tool"}])
        out = audit("--collections", FX / "collections.json", "--no-auto-pair", "--today", "2026-11-04")
        self.assertEqual(out["pairs_compared"], [])

    def test_context_error_stops(self):
        r = run("--collections", FX / "no_datahub.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Data Hub must be enabled", json.loads(r.stdout)["error"])

    def test_item_error_is_not_checked_and_redacted(self):
        out = audit("--collections", FX / "collections.json", "--config", f"products_prod={FX / 'config_error.json'}",
                    "--today", "2026-11-04")
        text = json.dumps(out)
        self.assertIn("Collection not found", text)
        self.assertNotIn("example.test", text)

    def test_bad_inputs(self):
        r = run("--collections", FX / "collections.json", "--config", "no_equals_sign")
        self.assertNotEqual(r.returncode, 0)
        r = run("--collections", FX / "collections.json", "--config", f"unknown={FX / 'config_prod.json'}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't in the collections list", json.loads(r.stdout)["error"])
        r = run("--collections", FX / "missing.json")
        self.assertEqual(r.returncode, 1)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "audit.json"
            r = subprocess.run([sys.executable, str(SCRIPT), *map(str, FULL), "--out", str(target)],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), json.loads(r.stdout))
            r = subprocess.run([sys.executable, str(SCRIPT), *map(str, FULL), "--out", str(Path(tmp) / "no/such/dir.json")],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            self.assertEqual(r.returncode, 1)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
