import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/voucher-pool-health"
SCRIPT = SKILL / "scripts/voucher_pool_health.py"
FIX = ROOT / "tests/fixtures/engagement/voucher-pool-health"


def f(name):
    return str(FIX / name)


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout


def full(*extra):
    args = ["--pools", f("pools.json"), "--today", "2026-11-04"]
    for i in range(1, 8):
        args += ["--pool-detail", f(f"pool_detail_{i}.json")]
    args += ["--codes", f"Welcome 10={f('codes_welcome_p1.json')}", "--codes", f"Welcome 10={f('codes_welcome_p2.json')}",
             "--codes", f"Partial={f('codes_partial.json')}",
             "--objects", f"scenario={f('scenarios.json')}", "--objects", f"email={f('email_detail.json')}",
             "--objects", f"banner={f('banners.json')}", "--calendar", f("calendar.json"),
             "--previous", f("pools_previous.json"), "--previous-date", "2026-10-25",
             "--expiry", "Black Friday 20=2026-11-20", *extra]
    code, out = run(*args)
    if code:
        raise AssertionError(out)
    return out, json.loads(out)


def pool(out, name):
    return next(p for p in out["pools"] if p["name"] == name)


def kinds(p):
    return {x["kind"]: x["priority"] for x in p["findings"]}


class VoucherPoolHealthTest(unittest.TestCase):
    def test_rules_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_burn_from_code_assignment_times_across_pages(self):
        _, out = full()
        p = pool(out, "Welcome 10")
        self.assertEqual(p["codes"], {"loaded": 60, "available": 5, "assigned": 28, "redeemed": 27})
        self.assertEqual(p["burn_per_day"], 1.0)  # 28 assignments in a 28-day window
        self.assertEqual(p["burn_source"], "code assigned_time")
        self.assertEqual(p["days_of_cover"], 5.0)
        self.assertEqual(p["rag"], "red")
        self.assertEqual(kinds(p)["runs_out"], "high")

    def test_codes_are_never_printed(self):
        raw, _ = full()
        self.assertNotIn("FAKE", raw)

    def test_demand_and_expiry_before_send(self):
        _, out = full()
        p = pool(out, "Black Friday 20")
        self.assertEqual(p["users"][0]["found_by"], ["jinja"])  # only in the email's Jinja, not in used_by
        self.assertEqual(p["burn_source"], "change in available codes over 10 days")
        self.assertEqual(p["planned_demand"], 180)
        self.assertEqual(p["planned_sends"][0]["next_send"], "2026-11-27")
        k = kinds(p)
        self.assertEqual(k["demand_exceeds"], "high")
        self.assertEqual(k["expiry_before_send"], "high")
        self.assertEqual(p["rag"], "red")

    def test_empty_pool_still_used_live(self):
        _, out = full()
        p = pool(out, "Spring 15")
        self.assertEqual(p["rag"], "red")
        self.assertIn("empty_but_live", kinds(p))
        self.assertNotIn("burn_unknown", kinds(p))

    def test_unused_and_archived_only(self):
        _, out = full()
        self.assertEqual(pool(out, "Old pool")["rag"], "not_in_use")
        self.assertIn("unused", kinds(pool(out, "Old pool")))
        p = pool(out, "Loyalty 5")
        self.assertEqual(p["users"][0]["status"], "archived")
        self.assertIn("no_live_use", kinds(p))

    def test_unknown_burn_and_partial_pages(self):
        _, out = full()
        self.assertEqual(pool(out, "VIP")["rag"], "unknown")
        p = pool(out, "Partial")
        self.assertEqual(p["burn_source"], "code assigned_time (newest pages only)")
        self.assertIn("burn_lower_bound", kinds(p))
        self.assertEqual(p["rag"], "green")

    def test_eql_assignments_used_when_codes_incomplete(self):
        _, out = full("--assignments", "Partial=84")
        p = pool(out, "Partial")
        self.assertEqual(p["burn_source"], "voucher event (EQL)")
        self.assertEqual(p["burn_per_day"], 3.0)
        self.assertEqual(p["days_of_cover"], 13.3)
        self.assertEqual(p["rag"], "amber")

    def test_eql_preferred_over_codes(self):
        _, out = full("--assignments", "Welcome 10=56")
        p = pool(out, "Welcome 10")
        self.assertEqual(p["burn_source"], "voucher event (EQL)")
        self.assertEqual(p["burn_per_day"], 2.0)

    def test_missing_available_count_is_not_an_empty_pool(self):
        code, raw = run("--pools", f("pools_missing_count.json"), "--pool-detail", f("pool_detail_1.json"),
                        "--objects", f"scenario={f('scenarios.json')}", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        p = json.loads(raw)["pools"][0]
        self.assertIsNone(p["available"])
        self.assertEqual(p["rag"], "unknown")
        self.assertEqual(kinds(p), {"counts_missing": "medium"})

    def test_empty_pool_has_no_cover_finding(self):
        _, out = full("--assignments", "Spring 15=28")
        k = kinds(pool(out, "Spring 15"))
        self.assertIn("empty_but_live", k)
        self.assertNotIn("low_cover", k)
        self.assertNotIn("runs_out", k)

    def test_pages_reaching_back_are_still_partial(self):
        _, out = full("--codes", f"VIP={f('codes_reach_back.json')}")
        p = pool(out, "VIP")
        self.assertEqual(p["burn_source"], "code assigned_time (newest pages only)")
        self.assertIn("burn_lower_bound", kinds(p))

    def test_eql_count_reads_the_count_column_only(self):
        _, out = full("--assignments", f"Partial={f('eql_two_columns.json')}")
        self.assertEqual(pool(out, "Partial")["burn_per_day"], 1.0)  # 20 + 8, not the revenue column

    def test_count_must_be_a_number_or_a_json_path(self):
        code, raw = run("--pools", f("pools.json"), "--assignments", "Partial=12abc", "--today", "2026-11-04")
        self.assertEqual(code, 1)
        code, raw = run("--pools", f("pools.json"), "--assignments", "Partial=missing.json", "--today", "2026-11-04")
        self.assertEqual(code, 1)
        self.assertIn("can't read", raw)

    def test_order_red_first_and_summary(self):
        _, out = full()
        self.assertEqual([p["rag"] for p in out["pools"]][:3], ["red", "red", "red"])
        self.assertEqual(out["summary"], {"red": 3, "amber": 0, "unknown": 1, "green": 1, "not_in_use": 2})

    def test_context_error_stops_and_url_is_redacted(self):
        code, out = run("--pools", f("error_project.json"))
        self.assertEqual(code, 1)
        self.assertIn("Project", out)
        self.assertNotIn("auth_key", out)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.json"
            code, out = run("--pools", f("pools.json"), "--today", "2026-11-04", "--out", str(target))
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
