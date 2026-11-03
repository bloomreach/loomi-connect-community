"""qbr_numbers.py uses the weekly-ecommerce-briefing method. With equal thresholds, the shared functions must agree,
apart from the differences the QBR's references/rules.json documents under `about`."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QBR = ROOT / "plugins/loomi-platform/skills/qbr-report/scripts/qbr_numbers.py"
BRIEFING = ROOT / "plugins/loomi-platform/skills/weekly-ecommerce-briefing/scripts/briefing_numbers.py"
C = ROOT / "tests/fixtures/platform/qbr_report/contract"
SHARED = ("peers", "low_conversion_ratio", "high_bounce_ratio", "high_bounce_min_points", "revenue_drop_ratio",
          "revenue_drop_min", "dead_end_bounce_pct")


def load(path, name):
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # never write __pycache__ into the skill folders
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = old


class MatchesWeeklyBriefingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = load(QBR, "qbr_numbers_under_test")
        cls.b = load(BRIEFING, "briefing_numbers_under_test")
        cls.b.RULES = dict(cls.b.RULES, **{k: cls.q.RULES[k] for k in SHARED})

    def test_number(self):
        for v in ("$1,000.00", "2.50%", "£3", " 7 ", 5, 3.25, "-4.5", None, "abc", "NA", float("nan"), True):
            self.assertEqual(self.q.number(v), self.b.number(v), repr(v))

    def test_median(self):
        for values in ([], [3.0], [5.0, 1.0], [4.0, 1.0, 9.0, 2.0], [1.0, 1.0, 2.0]):
            self.assertEqual(self.q.median(values), self.b.median(values))

    def test_money_movers(self):
        for path, label, key in ((C / "categories.json", "category", "cat_id"), (C / "products.json", "product_title", "prod_id"),
                                 (C / "brands.json", "brand", "brand")):
            q = self.q.money_movers(self.q.rows_of(str(path), key), label, 100, 5)
            b = self.b.money_movers(self.b.rows_of(str(path), key), label, 100, 5)
            self.assertEqual(q["considered"], b["considered"], label)
            for side in ("rising", "falling"):
                self.assertEqual([(i["name"].strip(), i["delta"]) for i in q[side]],
                                 [(str(i["name"]).strip(), i["delta"]) for i in b[side]], f"{label} {side}")

    def compare_lists(self, q, b, documented_dead_end_categories=False):
        b_issues = b["issues"]
        if documented_dead_end_categories:
            b_issues = [i for i in b_issues if not i["reasons"][0].startswith("dead end")]
        self.assertEqual([(t["name"], round(t["revenue"], 2)) for t in q["top"]],
                         [(str(t["name"]).strip(), round(t["revenue"], 2)) for t in b["top"]])
        self.assertEqual([(i["name"], [r.replace("vs previous quarter", "vs last week") for r in i["reasons"]],
                           i["revenue_at_stake"]) for i in q["issues"]],
                         [(str(i["name"]).strip(), i["reasons"], i["revenue_at_stake"]) for i in b_issues])

    def test_top_and_issues_searches(self):
        dead = [r.get("query") for r in self.b.rows_of(str(C / "dead_ends.json"), "query")
                if self.b.num(r.get("product_page_views")) == 0 and self.b.num(r.get("browse_sessions")) > 0]
        rows_q = self.q.rows_of(str(C / "queries.json"), "query")
        rows_b = self.b.rows_of(str(C / "queries.json"), "query")
        q = self.q.top_and_issues(rows_q, "query", "browse_sessions", 30, 10, 20, dead)
        b = self.b.top_and_issues(rows_b, "query", "browse_sessions", 30, 10, 20, dead)
        self.compare_lists(q, b)
        self.assertEqual((q["dead_ends"]["count"], q["dead_ends"]["sessions"], q["dead_ends"]["revenue_at_stake"]),
                         (b["dead_ends"]["count"], b["dead_ends"]["volume"], b["dead_ends"]["revenue_at_stake"]))

    def test_top_and_issues_categories(self):
        rows_q = self.q.rows_of(str(C / "categories.json"), "cat_id")
        rows_b = self.b.rows_of(str(C / "categories.json"), "cat_id")
        q = self.q.top_and_issues(rows_q, "category", "visits", 100, 10, 20)
        b = self.b.top_and_issues(rows_b, "category", "visits", 100, 10, 20)
        # Documented difference: the QBR never moves a category to a dead-end list.
        self.compare_lists(q, b, documented_dead_end_categories=True)


if __name__ == "__main__":
    unittest.main()
