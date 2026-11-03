import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-platform/skills/implementation-readiness/scripts/readiness_checks.py"
FIX = ROOT / "tests/fixtures/platform/implementation_readiness"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8")


FULL = ["--pixel", FIX / "pixel_partial.json", "--catalog-config", FIX / "catalog_config.json",
        "--products", FIX / "products.json", "--api", f"search={FIX / 'api_search.json'}",
        "--api", f"category={FIX / 'api_category.json'}", "--event-schema", FIX / "event_schema.json",
        "--customer-schema", FIX / "customer_schema_soft_only.json", "--consent", FIX / "consent.json",
        "--catalogs", FIX / "catalogs.json", "--catalog-items", FIX / "catalog_items_empty.json",
        "--scenarios", FIX / "scenarios.json", "--item", FIX / "feed_items.json", "--today", "2026-11-03"]


def items(*args):
    p = run(*args, "--json")
    assert p.returncode == 0, p.stderr + p.stdout
    out = json.loads(p.stdout)
    return out, {i["check"]: i for i in out["items"]}


class ReadinessChecksTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_full_run_verdict_and_blockers(self):
        out, by = items(*FULL)
        self.assertEqual(out["verdict"], "NOT READY")
        self.assertEqual(by["event checkout"]["status"], "RED")
        self.assertEqual(by["customer IDs"]["status"], "RED")
        self.assertEqual(by["catalog items"]["status"], "RED")
        self.assertEqual(by["product price filled"]["status"], "RED")  # "" is not a numeric price

    def test_stage_changes_no_traffic_status(self):
        _, pre = items(*FULL)
        _, live = items(*FULL, "--stage", "live")
        for check in ("pixel conversion-pageview", "category API traffic", "event purchase"):
            self.assertEqual(pre[check]["status"], "AMBER", check)
            self.assertEqual(live[check]["status"], "RED", check)

    def test_event_aliases_and_missing_properties(self):
        _, by = items(*FULL)
        self.assertEqual(by["event purchase_item (as order_item)"]["status"], "GREEN")
        self.assertIn("total_price", by["event cart_update"]["evidence"])
        self.assertEqual(by["event view_category"]["status"], "AMBER")  # optional

    def test_catalog_config_checks(self):
        _, by = items(*FULL)
        self.assertEqual(by["title searchable"]["status"], "GREEN")
        self.assertEqual(by["brand searchable"]["status"], "AMBER")
        self.assertEqual(by["category names searchable"]["status"], "AMBER")
        self.assertIn("2 of 3 custom attributes facetable", by["facetable attributes"]["evidence"])

    def test_flows_found_by_name(self):
        _, by = items(*FULL)
        self.assertEqual(by["welcome flow"]["status"], "GREEN")
        self.assertEqual(by["cart abandonment flow"]["status"], "AMBER")
        self.assertEqual(by["cart abandonment flow"]["owner"], "CRM")

    def test_extra_items_are_merged_and_suppress_reminders(self):
        _, by = items(*FULL)
        self.assertEqual(by["feed and index jobs"]["status"], "GREEN")  # lower-case status accepted
        self.assertEqual(by["pixel issue rates"]["status"], "GREEN")

    def test_missing_inputs_are_not_checked(self):
        out, by = items("--scope", "engagement", "--customer-schema", FIX / "customer_schema.json",
                        "--consent", FIX / "consent.json")
        self.assertEqual(by["customer IDs"]["status"], "GREEN")
        self.assertEqual(by["core events"]["status"], "NOT CHECKED")
        self.assertEqual(out["verdict"], "INCOMPLETE")
        self.assertFalse(any(i["area"].startswith("Discovery") for i in out["items"]))

    def test_empty_consent_is_red(self):
        _, by = items("--scope", "engagement", "--consent", FIX / "consent_empty.json")
        self.assertEqual(by["consent categories"]["status"], "RED")

    def test_markdown_lists_blockers_first(self):
        p = run(*FULL, "--title", "example / project", "--launch", "2026-11-20")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("17 days to go", p.stdout)
        self.assertLess(p.stdout.index("### Blockers"), p.stdout.index("### Amber"))

    def test_never_outputs_editor_names_or_margin_values(self):
        p = run(*FULL)
        self.assertNotIn("Example Editor", p.stdout)
        self.assertNotIn("0.4", p.stdout)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "checklist.md"
            p = run(*FULL, "--out", target)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)["verdict"], "NOT READY")
            self.assertTrue(target.read_text(encoding="utf-8").startswith("## Go-live readiness"))

    def test_error_response_stops(self):
        p = run("--scope", "engagement", "--event-schema", FIX / "denied.json")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn("ACCESS_DENIED", json.loads(p.stdout)["error"])

    def test_rules_file_is_complete(self):
        rules = json.loads((SCRIPT.parent.parent / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})


if __name__ == "__main__":
    unittest.main()
