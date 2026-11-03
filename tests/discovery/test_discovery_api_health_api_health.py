"""Tests for discovery-api-health's api_health.py. The data is synthetic: the healthy and broken daily
get_discovery_api_requests series are built in a temp folder by build_scenarios() below; the monthly unique
visitor results and the error cases are small committed fixtures."""
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
SHARES = {"keyword": .30, "category": .40, "suggest": .10, "bestseller": .05}


def usage_result(rows):
    return {"success": True, "data": {"isSuccessful": True, "body": {"group_definitions": [], "results": rows}},
            "error": None}


def daily_result(values):
    return usage_result([{"groups": [], "total": {"request_count": {"value": str(int(v))}},
                          "time_period_start": d.isoformat(), "time_period_end": (d + timedelta(days=1)).isoformat()}
                         for d, v in values])


def build_scenarios(folder):
    """Write 36 days (to the partial "today", 2026-11-03) of each series for a healthy and a broken account.

    Weekdays carry 100,000 requests and weekends 80,000, split across four request types plus 15% 'other'. The
    broken account has, on purpose: a category drop on 31 Oct, a 5xx spike on 1 Nov, and on 2 Nov keyword search
    stopping, an autosuggest surge, a 4xx spike under the fixed limit, a staging share jump and a UK site down 60%.
    """
    start = date(2026, 9, 29)
    days = [start + timedelta(days=i) for i in range(36)]
    for scen in ("healthy", "broken"):
        series = {name: [] for name in ["total", "5xx", "4xx", "staging", "site_uk"] + [f"type_{k}" for k in SHARES]}
        for d in days:
            t = (80000 if d.weekday() >= 5 else 100000) * (1 + (d.day % 3 - 1) * 0.02)
            p = {k: t * share for k, share in SHARES.items()}
            e5, e4, staging, uk = 5, 50, t * 0.01, t * 0.2
            if scen == "broken":
                if d == date(2026, 10, 31):
                    p["category"] *= 0.7
                if d == date(2026, 11, 1):
                    e5 = t * 0.03
                if d == date(2026, 11, 2):
                    p["keyword"] = 0
                    p["suggest"] *= 2.5
                    e4 = 400
                    staging = t * 0.15
                    uk = t * 0.2 * 0.4
            t = sum(p.values()) + t * 0.15
            if d == days[-1]:
                t *= 0.3  # the partial current day, which must be ignored
            for name, v in [("total", t), ("5xx", e5), ("4xx", e4), ("staging", staging), ("site_uk", uk)] + \
                    [(f"type_{k}", p[k]) for k in SHARES]:
                series[name].append((d, v))
        for name, values in series.items():
            (Path(folder) / f"{scen}_{name}.json").write_text(json.dumps(daily_result(values)), encoding="utf-8")


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, timeout=60)
        written = sorted(p.name for p in Path(tmp).iterdir())
    out = json.loads(r.stdout) if r.stdout.strip() else None
    return r.returncode, out, r.stderr, written


def scenario(folder, name, muv="muv_within_contract.json"):
    f = Path(folder)
    args = ["--series", f"total={f / f'{name}_total.json'}"]
    for t in SHARES:
        args += ["--series", f"type:{t}={f / f'{name}_type_{t}.json'}"]
    args += ["--series", f"status:5xx={f / f'{name}_5xx.json'}", "--series", f"status:4xx={f / f'{name}_4xx.json'}",
             "--series", f"env:staging={f / f'{name}_staging.json'}", "--series", f"site:uk={f / f'{name}_site_uk.json'}",
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
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = cls.tmp.name
        build_scenarios(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_healthy_is_green(self):
        code, out, err, _ = run(*scenario(self.data, "healthy"))
        self.assertEqual(code, 0, err)
        self.assertEqual(out["overall"], "GREEN", out["checks"])
        # The partial current day is never judged; the baseline is the 28 days before the recent window.
        self.assertEqual(out["recent_days"], ["2026-10-31", "2026-11-01", "2026-11-02"])
        self.assertEqual(out["baseline"], {"from": "2026-10-03", "to": "2026-10-30"})
        self.assertIn("type:other", by_series(out))
        self.assertEqual(out["notes"], [])

    def test_broken_flags_each_problem(self):
        code, out, _, _ = run(*scenario(self.data, "broken", "muv_over_contract.json"))
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
            code, out, _, written = run(*scenario(self.data, "healthy"), "--out", target)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), out)
        self.assertEqual(written, [])

    def test_account_list_errors_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            leak = Path(tmp) / "leak.json"
            leak.write_text(json.dumps({"success": False, "error": "Unknown account_name 'acme'. Available accounts: "
                                        "alpha_shop, beta_store, gamma_retail, delta_outlet"}), encoding="utf-8")
            plain = Path(tmp) / "plain.json"
            plain.write_text(json.dumps({"success": False, "error": "x" * 500}), encoding="utf-8")
            bad_rows = Path(tmp) / "rows.json"
            bad_rows.write_text(json.dumps(usage_result(["not a row"])), encoding="utf-8")
            code, out, _, _ = run("--series", f"total={leak}")
            self.assertEqual(code, 1)
            self.assertIn("Ask the user to check the account name", out["error"])
            self.assertNotIn("beta_store", out["error"])
            code, out, _, _ = run("--series", f"total={plain}")
            self.assertEqual(code, 1)
            self.assertNotIn("x" * 201, out["error"])
            code, out, _, _ = run("--series", f"total={bad_rows}")
            self.assertEqual(code, 1)
            self.assertIn("something other than result rows", out["error"])

    def test_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            healthy_total = write_series(tmp, "total.json", [1000] * 35)
            healthy_keyword = write_series(tmp, "keyword.json", [300] * 35)
            self._bad_input(healthy_total, healthy_keyword)

    def _bad_input(self, healthy_total, healthy_keyword):
        for args, text in [(["--series", f"total={FX / 'denied.json'}"], "ACCESS_DENIED"),
                           (["--series", f"total={FX / 'not_successful.json'}"], "reported a failure"),
                           (["--series", f"total={FX / 'no_body.json'}"], "no data.body.results"),
                           (["--series", f"total={FX / 'monthly.json'}"], "granularity 'daily'"),
                           (["--series", f"total={FX / 'missing.json'}"], "can't read it"),
                           (["--series", f"type:keyword={healthy_keyword}"], "total=<file> (no filter) is required"),
                           (["--series", f"total={healthy_total}", "--series", f"total={healthy_total}"],
                            "only be given once"),
                           ([], "give at least"),
                           (["--series", f"total={healthy_total}", "--today", "2026-09-01"], "no complete days")]:
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

    def test_test_data_matches_the_call_plan(self):
        # The built series use the same request types as the call plan in rules.json.
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(list(SHARES), rules["request_types"])


if __name__ == "__main__":
    unittest.main()
