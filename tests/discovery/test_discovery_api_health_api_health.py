"""Tests for discovery-api-health's api_health.py. The fixtures are synthetic: 35 days of daily
get_discovery_api_requests results (healthy and broken), and monthly unique visitor results."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-api-health"
SCRIPT = SKILL / "scripts/api_health.py"
FX = ROOT / "tests/fixtures/discovery/api_health"
TODAY = "2026-11-03"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, timeout=60)
        written = sorted(p.name for p in Path(tmp).iterdir())
    out = json.loads(r.stdout) if r.stdout.strip() else None
    return r.returncode, out, r.stderr, written


def scenario(name, muv="muv_within_contract.json"):
    args = ["--series", f"total={FX / f'{name}_total.json'}"]
    for t in ("keyword", "category", "suggest", "bestseller"):
        args += ["--series", f"type:{t}={FX / f'{name}_type_{t}.json'}"]
    args += ["--series", f"status:5xx={FX / f'{name}_5xx.json'}", "--series", f"status:4xx={FX / f'{name}_4xx.json'}",
             "--series", f"env:staging={FX / f'{name}_staging.json'}", "--series", f"site:uk={FX / f'{name}_site_uk.json'}",
             "--muv", FX / muv, "--today", TODAY]
    return args


def by_series(out):
    return {c["series"]: c for c in out["checks"]}


def write_series(folder, name, values, start=date(2026, 9, 29)):
    rows = [{"groups": [], "total": {"request_count": {"value": str(v)}},
             "time_period_start": (start + timedelta(days=i)).isoformat()} for i, v in enumerate(values)]
    path = Path(folder) / name
    path.write_text(json.dumps({"success": True, "data": {"isSuccessful": True, "body": {"results": rows}}}),
                    encoding="utf-8")
    return path


class ApiHealthTest(unittest.TestCase):
    def test_healthy_is_green(self):
        code, out, err, _ = run(*scenario("healthy"))
        self.assertEqual(code, 0, err)
        self.assertEqual(out["overall"], "GREEN", out["checks"])
        # The partial current day is never judged; the baseline is the 28 days before the recent window.
        self.assertEqual(out["recent_days"], ["2026-10-31", "2026-11-01", "2026-11-02"])
        self.assertEqual(out["baseline"], {"from": "2026-10-03", "to": "2026-10-30"})
        self.assertIn("type:other", by_series(out))
        self.assertEqual(out["notes"], [])

    def test_broken_flags_each_problem(self):
        code, out, _, _ = run(*scenario("broken", "muv_over_contract.json"))
        self.assertEqual(code, 0)
        self.assertEqual(out["overall"], "RED")
        s = by_series(out)
        expected = {"status:5xx": ("RED", "2026-11-01"), "type:keyword": ("RED", "2026-11-02"),
                    "site:uk": ("RED", "2026-11-02"), "status:4xx": ("AMBER", "2026-11-02"),
                    "env:staging": ("AMBER", "2026-11-02"), "type:category": ("AMBER", "2026-10-31"),
                    "type:suggest": ("AMBER", "2026-11-02"), "muv": ("RED", "2026-10")}
        for name, (status, day) in expected.items():
            self.assertEqual((s[name]["status"], s[name]["date"]), (status, day), name)
        self.assertIn("no requests", s["type:keyword"]["evidence"])
        self.assertIn("a spike", s["status:4xx"]["evidence"])
        self.assertIn("2.5×", s["type:suggest"]["evidence"])
        self.assertEqual(s["type:bestseller"]["status"], "GREEN")
        # Red first, then amber, then green.
        order = [c["status"] for c in out["checks"]]
        self.assertEqual(order, sorted(order, key=["RED", "AMBER", "GREEN"].index))

    def test_muv_forecast_and_contract(self):
        _, out, _, _ = run("--muv", FX / "muv_over_contract.json", "--today", TODAY)
        self.assertEqual(out["muv"]["forecast_this_month"], 940000)  # average of Aug, Sep, Oct
        self.assertEqual(out["muv"]["contracted_muv"], 1000000)
        self.assertEqual([m["usage_pct"] for m in out["muv"]["months"]], [80.0, 85.0, 95.0, 102.0])
        _, out, _, _ = run("--muv", FX / "muv_within_contract.json", "--today", TODAY)
        self.assertEqual(out["overall"], "GREEN")
        self.assertIn("51% of the contracted limit", out["checks"][0]["evidence"])

    def test_unpublished_month_is_left_out(self):
        # On 1 December, November still reads 0 (it's published on the 2nd), so October is the last complete month.
        _, out, _, _ = run("--muv", FX / "muv_over_contract.json", "--today", "2026-12-01")
        self.assertEqual(out["muv"]["months"][-1]["month"], "2026-10")
        self.assertEqual(out["overall"], "RED")

    def test_forecast_alone_can_be_amber(self):
        rows = [{"groups": [], "total": {"contracted_muv": {"value": "1000"}, "muv": {"value": str(v)}},
                 "time_period_start": m} for m, v in (("2026-08", 990), ("2026-09", 950), ("2026-10", 800))]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "muv.json"
            path.write_text(json.dumps({"success": True, "data": {"isSuccessful": True, "body": {"results": rows}}}),
                            encoding="utf-8")
            _, out, _, _ = run("--muv", path, "--today", TODAY)
        check = out["checks"][0]
        self.assertEqual((check["status"], check["date"]), ("AMBER", "2026-11 forecast"))  # 80% last month, 91% forecast

    def test_no_contract(self):
        _, out, _, _ = run("--muv", FX / "muv_no_contract.json", "--today", TODAY)
        self.assertEqual(out["overall"], "GREEN")
        self.assertIn("no contracted limit", out["checks"][0]["evidence"])
        self.assertIsNone(out["muv"]["contracted_muv"])

    def test_no_complete_month(self):
        _, out, _, _ = run("--muv", FX / "muv_no_contract.json", "--today", "2026-09-15")
        self.assertIn("no complete month", out["checks"][0]["evidence"])

    def test_small_series_and_unchecked_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tiny = write_series(tmp, "tiny.json", [10] * 35)
            total = write_series(tmp, "total.json", [1000] * 35)
            code, out, err, _ = run("--series", f"total={total}", "--series", f"region:eu={tiny}",
                                    "--series", f"status:2xx={tiny}", "--series", f"env:production={tiny}",
                                    "--today", "2026-11-03")
        self.assertEqual(code, 0, err)
        self.assertEqual(by_series(out)["region:eu"]["evidence"], "too little traffic to judge")
        self.assertTrue(any("status:2xx isn't checked" in n for n in out["notes"]))
        self.assertTrue(any("env:production isn't checked" in n for n in out["notes"]))

    def test_short_baseline_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            total = write_series(tmp, "total.json", [1000] * 6, start=date(2026, 10, 28))
            _, out, _, _ = run("--series", f"total={total}", "--today", "2026-11-03")
        self.assertTrue(any("Only 3 baseline day(s)" in n for n in out["notes"]))

    def test_out_file_and_nothing_else_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "health.json"
            code, out, _, written = run(*scenario("healthy"), "--out", target)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), out)
        self.assertEqual(written, [])

    def test_bad_input(self):
        for args, text in [(["--series", f"total={FX / 'denied.json'}"], "ACCESS_DENIED"),
                           (["--series", f"total={FX / 'not_successful.json'}"], "reported a failure"),
                           (["--series", f"total={FX / 'no_body.json'}"], "no data.body.results"),
                           (["--series", f"total={FX / 'monthly.json'}"], "granularity 'daily'"),
                           (["--series", f"total={FX / 'missing.json'}"], "can't read it"),
                           (["--series", f"type:keyword={FX / 'healthy_type_keyword.json'}"], "total=<file> (no filter) is required"),
                           (["--series", f"total={FX / 'healthy_total.json'}", "--series", f"total={FX / 'healthy_total.json'}"],
                            "only be given once"),
                           ([], "give at least"),
                           (["--series", f"total={FX / 'healthy_total.json'}", "--today", "2026-09-01"], "no complete days")]:
            code, out, _, _ = run(*args)
            self.assertEqual(code, 1, args)
            self.assertIn(text, out["error"])
        for args in (["--series", "bogus=x.json"], ["--series", "type=x.json"], ["--today", "03/11/2026"]):
            code, _, err, _ = run(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("error:", err)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
