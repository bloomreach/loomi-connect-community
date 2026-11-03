import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "loomi-discovery" / "skills" / "discovery-change-qa"
SCRIPT = SKILL / "scripts" / "change_preview.py"
FIX = ROOT / "tests" / "fixtures" / "discovery" / "change_qa"
NOW = "2026-11-03T00:00:00Z"


def run(*args):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)


def preview(change, *args):
    p = run("--change", FIX / change, "--now", NOW, *args)
    if p.returncode:
        raise AssertionError(p.stdout + p.stderr)
    return json.loads(p.stdout)


def checks(result, severity=None):
    return [f["check"] for f in result["findings"] if severity in (None, f["severity"])]


def grid(query, name):
    return ("--grid", f"{query}={FIX / name}")


class ChangePreviewTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references" / "rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))

    def test_raw_ranking_rule_simulation_and_checks(self):
        r = preview("change_ranking_raw.json", *grid("dress", "grid_dress.json"),
                    "--queries", FIX / "queries_perf.json", "--products", FIX / "products_perf.json",
                    "--existing", FIX / "existing_rules.json", "--page-size", 5)
        self.assertEqual(r["change"]["type"], "ranking")
        self.assertEqual(r["affected"]["revenue"], 52000.0)  # exact match: "black dress" isn't touched
        p = r["previews"][0]
        self.assertTrue(p["simulated"])
        # Boosted products first in boost order, the missing pin at slot 2, then the brand boost.
        self.assertEqual([x["pid"] for x in p["after"]], ["p7", "p99", "p9", "p6", "p8"])
        self.assertIn("pinned to slot 2", p["after"][1]["why"])
        # The in-grid banner (a content doc) is never ranked as a product.
        self.assertNotIn(None, [x["pid"] for x in p["before"]])
        found = {f["check"]: f for f in r["findings"]}
        self.assertEqual(found["top sellers"]["evidence"][0]["pid"], "p1")
        self.assertIn("Leather Belt", found["relevance"]["issue"])
        self.assertIn("p99", found["not in results"]["issue"])
        self.assertIn("Acme Sequin Dress", found["stock"]["issue"])
        self.assertIn("Acme", found["brand mix"]["issue"])
        self.assertIn("strength", found)
        self.assertIn("schedule", found)  # "Holiday sale" with no end date
        # Existing rules: 800001 (enabled) and 800004 (scheduled later, overlaps an open-ended change) stack;
        # expired, disabled and the rule itself are ignored.
        conflicts = [f["issue"] for f in r["findings"] if f["check"] == "conflict"]
        self.assertEqual(len(conflicts), 2)
        self.assertTrue(any("800001" in c for c in conflicts) and any("800004" in c for c in conflicts))
        self.assertEqual(r["verdict"], "GO WITH CAUTION")

    def test_clean_change_is_go(self):
        r = preview("change_ranking_clean.json", *grid("dress", "grid_dress.json"),
                    "--queries", FIX / "queries_perf.json", "--products", FIX / "products_perf.json",
                    "--page-size", 5)
        self.assertEqual(r["verdict"], "GO", r["findings"])
        self.assertEqual([x["pid"] for x in r["previews"][0]["after"]], ["p3", "p5", "p1", "p2", "p4"])

    def test_rule_mechanics(self):
        r = preview("change_ranking_conflicts.json", *grid("dress", "grid_dress.json"), "--page-size", 5)
        self.assertEqual(r["verdict"], "NO-GO")
        self.assertEqual(sorted(checks(r, "blocker")), ["contradiction", "pins"])
        self.assertIn("attribute values", checks(r, "warning"))  # brand "Nobody " isn't in the results
        self.assertIn("pins", checks(r, "nitpick"))  # slot 30 is below page one
        self.assertTrue(any("color isn't in the saved grid" in n for n in r["not_checked"]))
        self.assertTrue(any("no query or category performance" in n for n in r["not_checked"]))

    def test_schedule(self):
        r = preview("change_schedule.json")
        issues = [f["issue"] for f in r["findings"] if f["check"] == "schedule"]
        self.assertTrue(any("already passed" in i for i in issues))
        self.assertTrue(any("start date isn't before" in i for i in issues))
        self.assertEqual(r["verdict"], "NO-GO")

    def test_global_search_rule_covers_searches_not_categories(self):
        r = preview("change_global.json", "--queries", FIX / "queries_perf.json",
                    "--categories", FIX / "categories_perf.json")
        self.assertIn("scope", checks(r, "warning"))
        self.assertEqual({row["kind"] for row in r["affected"]["rows"]}, {"query"})
        self.assertTrue(any("No grid preview for query 'dress'" in n for n in r["not_checked"]))
        self.assertEqual(r["verdict"], "GO WITH CAUTION")

    def test_category_rule_with_recall_and_pin(self):
        r = preview("change_recall.json", *grid("cat-dresses", "grid_dress.json"),
                    "--categories", FIX / "categories_perf.json", "--queries", FIX / "queries_perf.json",
                    "--page-size", 5)
        self.assertEqual(r["affected"]["count"], 1)
        self.assertEqual(r["previews"][0]["after"][0]["pid"], "p50")
        self.assertNotIn("not in results", checks(r))  # it's added to recall
        self.assertEqual(r["verdict"], "GO")

    def test_media_and_facet_rules(self):
        r = preview("change_no_queries.json")
        self.assertEqual(sorted(checks(r, "blocker")), ["media", "scope"])
        self.assertIn("media", checks(r, "warning"))  # http image
        for name in ("change_facet.json", "change_facet_raw.json"):
            self.assertEqual(checks(preview(name), "blocker"), ["facets"], name)

    def test_real_after_grid(self):
        r = preview("change_media.json", *grid("dress", "grid_dress.json"),
                    "--grid-after", f"dress={FIX / 'grid_dress_after.json'}",
                    "--existing", FIX / "existing_media.json", "--page-size", 5)
        p = r["previews"][0]
        self.assertFalse(p["simulated"])
        self.assertEqual(p["pushed_off"], [])
        self.assertIn("banners", checks(r, "nitpick"))
        self.assertIn("conflict", checks(r, "warning"))  # media rules list as ruleType "campaign"

    def test_zero_results_ab_test_and_redirect_conflicts(self):
        r = preview("change_ranking_clean.json", *grid("dress", "grid_empty.json"),
                    "--existing", FIX / "existing_ab.json", "--existing", FIX / "existing_redirects.json")
        self.assertEqual(checks(r, "blocker"), ["a/b test"])
        self.assertIn("zero results", checks(r, "warning"))
        self.assertIn("conflict", checks(r, "warning"))
        self.assertFalse(any("isn't in the saved grid" in n for n in r["not_checked"]))

    def test_running_experiments(self):
        r = preview("change_ranking_clean.json", *grid("dress", "grid_dress.json"),
                    "--experiments", FIX / "experiments_running.json", "--page-size", 5)
        found = [(f["severity"], f["issue"]) for f in r["findings"] if f["check"] == "a/b test"]
        self.assertIn(("blocker", "Running experiment 'Dress ranking test' covers dress."), found)
        self.assertTrue(any(s == "nitpick" and "Shoes test" in i for s, i in found))

    def test_redirect(self):
        r = preview("change_redirect_raw.json", "--queries", FIX / "queries_perf.json",
                    "--existing", FIX / "existing_for_redirect.json")
        self.assertEqual(r["change"]["url"], "http://shop.example.test/sale page")
        issues = " | ".join(f["issue"] for f in r["findings"])
        self.assertIn("contains spaces", issues)
        self.assertIn("uses http", issues)
        self.assertIn("'sale dresses', which earns 15000.00", issues)  # phrase match hijack
        self.assertIn("'sale' earns 4000.00", issues)
        self.assertNotIn("summer sale", issues)  # below redirect_min_revenue
        self.assertNotIn("looks unfinished", issues)  # a .test host isn't a placeholder
        self.assertIn("scope", checks(r, "warning"))  # one-word phrase match
        self.assertIn("conflict", checks(r, "nitpick"))
        self.assertEqual(r["verdict"], "NO-GO")

    def test_redirect_urls(self):
        cases = {"change_redirect_placeholder.json": ("blocker", "looks unfinished"),
                 "change_redirect_noscheme.json": ("warning", "no scheme"),
                 "change_redirect_bad.json": ("blocker", "isn't a web page"),
                 "change_redirect_empty.json": ("blocker", "no destination URL")}
        for name, (severity, text) in cases.items():
            r = preview(name)
            urls = [(f["severity"], f["issue"]) for f in r["findings"] if f["check"] == "url"]
            self.assertTrue(any(s == severity and text in i for s, i in urls), (name, urls))
        bad = preview("change_redirect_bad.json")
        self.assertEqual(len([f for f in bad["findings"] if f["check"] == "url"]), 1)

    def test_synonym_direction_and_duplicate(self):
        r = preview("change_synonym_raw.json", *grid("frock", "grid_frock.json"),
                    "--target-grid", f"dress={FIX / 'grid_dress.json'}",
                    "--target-grid", f"gown={FIX / 'grid_gown_empty.json'}",
                    "--synonyms", FIX / "synonyms_list.json")
        self.assertEqual(r["change"]["targets"], ["dress", "gown", "frock"])
        self.assertEqual(sorted(checks(r)), ["direction", "duplicate"])  # "dress" results look like frocks

    def test_synonym_without_source_results(self):
        r = preview("change_synonym_raw.json", *grid("frock", "grid_frock_empty.json"),
                    "--target-grid", f"dress={FIX / 'grid_dress.json'}",
                    "--target-grid", f"gown={FIX / 'grid_gown_empty.json'}")
        self.assertEqual(checks(r), ["no results"])
        self.assertTrue(any("no results of its own" in n for n in r["not_checked"]))

    def test_synonym_broadening_and_noop(self):
        r = preview("change_synonym_broad.json", *grid("dress", "grid_dress.json"),
                    "--target-grid", f"party={FIX / 'grid_party.json'}")
        self.assertEqual(checks(r, "warning"), ["broadening"])
        r = preview("change_synonym_noop.json", "--target-grid", f"party={FIX / 'grid_party.json'}")
        self.assertEqual(checks(r), ["no-op"])

    def test_missing_target_grid_is_not_checked(self):
        r = preview("change_synonym_broad.json", *grid("dress", "grid_dress.json"))
        self.assertTrue(any("'party': no grid given" in n for n in r["not_checked"]))
        self.assertEqual(r["verdict"], "GO WITH CAUTION")

    def test_grid_as_plain_list(self):
        r = preview("change_ranking_clean.json", *grid("dress", "grid_list.json"), "--page-size", 5)
        self.assertEqual(r["previews"][0]["results"], 2)

    def test_missing_revenue_is_not_zero(self):
        data = json.loads((FIX / "queries_perf.json").read_text(encoding="utf-8"))
        data["data"]["rows"][0]["revenue"] = "NA"
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "queries.json"
            q.write_text(json.dumps(data), encoding="utf-8")
            r = preview("change_ranking_raw.json", *grid("dress", "grid_dress.json"), "--queries", q, "--page-size", 5)
        self.assertEqual(r["affected"]["revenue_missing"], 1)
        self.assertIsNone(r["affected"]["rows"][0]["revenue"])
        self.assertEqual(r["affected"]["revenue"], 0)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            p = run("--change", FIX / "change_schedule.json", "--now", NOW, "--out", out)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["verdict"], "NO-GO")

    def test_errors(self):
        p = run("--change", FIX / "change_ranking_clean.json", "--existing", FIX / "denied.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("ACCESS_DENIED", json.loads(p.stdout)["error"])
        p = run("--change", FIX / "change_ranking_clean.json", "--grid", "dress")
        self.assertEqual(p.returncode, 1)
        self.assertIn("QUERY=path", p.stdout)
        p = run("--change", FIX / "queries_perf.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("change-format.md", p.stdout)
        p = run("--change", FIX / "change_ranking_clean.json", "--grid", f"dress={FIX / 'queries_perf.json'}")
        self.assertEqual(p.returncode, 1)
        self.assertIn("data.response.docs", p.stdout)


if __name__ == "__main__":
    unittest.main()
