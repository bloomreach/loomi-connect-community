import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-product-data/skills/attribute-normaliser"
SCRIPT = SKILL / "scripts/attribute_clusters.py"
FIX = ROOT / "tests/fixtures/product_data/attribute-normaliser"
ATTRS = "colors,sku_color,sizes,material,brand,length"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8")


def clusters(*extra):
    p = run(FIX / "grid_products.json", "--attributes", ATTRS, *extra)
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout)
    return out, {r["attribute"]: r["top_clusters"] for r in out["results"]}


def members(cluster_list):
    """{canonical: {value: member}}"""
    return {c["canonical"]: {m["value"]: m for m in c["members"]} for c in cluster_list}


class AttributeClustersTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertTrue(rules["about"])
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys - set(rules["notes"]), set())
        self.assertEqual(set(rules["notes"]) - keys, set())

    def test_navy_cluster(self):
        _, c = clusters()
        navy = members(c["colors"])["Navy"]
        self.assertEqual(set(navy), {"NAVY", "navy blue", "Nvy"})
        self.assertEqual(navy["navy blue"]["products"], 2)
        self.assertIn("synonym table", navy["navy blue"]["reason"])
        self.assertEqual(navy["Nvy"]["confidence"], "high")

    def test_navy_and_black_never_merge(self):
        _, c = clusters()
        for cl in c["colors"]:
            values = {cl["canonical"], *(m["value"] for m in cl["members"])}
            self.assertFalse({"Navy", "Black"} <= values)
        self.assertIn("Black", members(c["colors"]))

    def test_sizes_materials_spacing(self):
        _, c = clusters()
        self.assertEqual(set(members(c["sizes"])["XL"]), {"X-Large", "x large"})
        cotton = members(c["material"])["Cotton"]
        self.assertEqual(cotton["100% Cotton"]["reason"], "removed '100%'")
        brand = members(c["brand"])["Example Brand"]
        self.assertEqual(brand["Example Brand "]["reason"], "spacing")  # a trailing space is kept and fixed

    def test_real_differences_stay_apart(self):
        _, c = clusters()
        mats = {cl["canonical"]: cl for cl in c["material"]}
        for a, b in (("Wool", "Wood"), ("Planters", "Platters")):
            for cl in mats.values():
                values = {cl["canonical"], *(m["value"] for m in cl["members"])}
                self.assertFalse({a, b} <= values, f"{a} and {b} merged")

    def test_typos_are_low_confidence_for_review(self):
        _, c = clusters()
        poly = members(c["material"])["Polyester"]["Polyster"]
        self.assertEqual((poly["confidence"], poly["review"]), ("low", True))
        self.assertIn("edit distance 1", poly["reason"])
        ex = members(c["brand"])["Example Brand"]["Exmaple Brand"]
        self.assertEqual(ex["confidence"], "low")

    def test_units(self):
        _, c = clusters()
        m = members(c["length"])
        self.assertEqual(m["32in"]['32"']["confidence"], "high")
        self.assertEqual(m["32in"]["81 cm"]["confidence"], "medium")
        self.assertIn("8 x 10 ft", m["8' x 10'"])
        flat = {v for cl in c["length"] for v in [cl["canonical"], *(x["value"] for x in cl["members"])]}
        self.assertNotIn("99 cm", flat)  # same system, not equal: never merged

    def test_variants_counted(self):
        _, c = clusters()
        self.assertEqual(members(c["sku_color"])["navy"]["Navy"]["products"], 1)

    def test_facets_and_attribute_list(self):
        p = run("--facets", FIX / "grid_facets.json", "--facet-attributes", FIX / "facet_attributes.json")
        out = json.loads(p.stdout)
        res = {r["attribute"]: r for r in out["results"]}
        grey = members(res["colors"]["top_clusters"])["gray"]["grey"]
        self.assertEqual(grey["products"], 70)
        metal = members(res["material"]["top_clusters"])["Metal"]["metal"]
        self.assertEqual(metal["products"], 2)
        self.assertEqual(res["material"]["source"], "facets")
        self.assertIn("collection", out["attributes_not_found"])
        self.assertNotIn("margin", p.stdout)
        self.assertNotIn("omni_score_views", p.stdout)
        self.assertNotIn("inStock", p.stdout)

    def test_never_reads_margin(self):
        p = run(FIX / "grid_products.json", "--attributes", "margin,colors")
        self.assertNotIn("margin", json.loads(p.stdout)["attributes_not_found"] + [r["attribute"] for r in json.loads(p.stdout)["results"]])

    def test_csv_mapping_escapes_formulas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.csv"
            p = run(FIX / "grid_products.json", "--attributes", ATTRS, "--csv", path)
            self.assertEqual(p.returncode, 0, p.stdout)
            with open(path, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), ["attribute", "value", "canonical", "products", "confidence", "review", "reason"])
        red = next(r for r in rows if r["canonical"] == "red")
        self.assertEqual(red["value"], "'+Red")
        self.assertFalse(any(r["value"].startswith(("=", "+", "-", "@")) for r in rows))

    def test_deterministic(self):
        self.assertEqual(clusters()[0], clusters()[0])


if __name__ == "__main__":
    unittest.main()
