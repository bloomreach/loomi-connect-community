"""Tests for discovery-query-rule-impact's rule_impact.py. The fixtures in
tests/fixtures/discovery/query_rule_impact/ are synthetic (made-up products and rule IDs)."""
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-query-rule-impact"
SCRIPT = SKILL / "scripts/rule_impact.py"
FX = ROOT / "tests/fixtures/discovery/query_rule_impact"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp, timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def full(*extra, query="query_perf.json", rpv_table="rpv_table.json"):
    return run("--baseline", FX / "baseline.json",
               "--toggled", f"900001={FX / 'off_900001.json'}", "--toggled", f"900002={FX / 'off_900002.json'}",
               "--toggled", f"950001={FX / 'off_950001_no_echo.json'}", "--toggled", f"all_algo={FX / 'off_all_algo.json'}",
               "--toggled", f"all={FX / 'off_all.json'}",
               "--query-perf", FX / query, "--query", "gown", "--page-size", "5",
               "--product-rpv", FX / rpv_table, "--product-rpv", f"H1={FX / 'rpv_H1.json'}",
               "--product-rpv", f"D={FX / 'rpv_D_not_found.json'}", *extra)


def result(out, name):
    return next(r for r in out["results"] if r["name"] == name)


class RuleImpactTest(unittest.TestCase):
    def test_pinned_products_and_moves(self):
        code, out, _ = full()
        self.assertEqual(code, 0)
        r = result(out, "900001")
        self.assertEqual([(x["pid"], x["kinds"], x["position"]) for x in r["applied"]],
                         [("X1", ["boost"], 1), ("X2", ["boost"], 2)])  # banner row skipped: X1 is position 1
        self.assertEqual([(m["pid"], m["with_rule"], m["without_rule"]) for m in r["moves"]],
                         [("X1", 1, 3), ("X2", 2, 5), ("A", 3, 1), ("B", 4, 2), ("C", 5, 4)])
        # 900002 doesn't change X1/X2's boost, so it isn't credited with it
        self.assertEqual(result(out, "900002")["applied"], [])

    def test_estimate_maths_exact(self):
        _, out, _ = full()
        # (0.12-0.075)*2 + (0.09-0.055)*4 + (0.075-0.12)*10 + (0.065-0.09)*8 + (0.055-0.065)*5 = -0.47; x 1000 visits
        r = result(out, "900001")
        self.assertEqual(r["estimated_effect"], "-470.00")
        self.assertEqual(r["share_of_query_revenue"], "-0.0235")
        self.assertEqual((r["verdict"], r["priority"]), ("hurts", "high"))
        self.assertEqual(result(out, "900002")["estimated_effect"], "-1045.00")

    def test_exact_query_row_not_substring(self):
        _, out, _ = full()
        self.assertEqual(out["query_metrics"]["visits"], 1000)  # not the "gowns" row

    def test_scaled_to_query_views(self):
        _, out, _ = full(query="query_perf_views.json")  # also matches "Gown" ignoring case
        curve = [Decimal(str(w)) for w in RULES["position_weights"]][:5]
        scale = Decimal("0.8") / sum(curve)
        expected = (Decimal("-0.47") * scale * 1000).quantize(Decimal("0.01"))
        self.assertEqual(result(out, "900001")["estimated_effect"], str(expected))
        self.assertEqual(out["query_metrics"]["product_views_per_visit"], "0.80")

    def test_hidden_via_num_found_and_pid_diff(self):
        _, out, _ = full()
        r = result(out, "900002")
        self.assertEqual(r["hidden_count"], 1)
        self.assertEqual(r["num_found"], {"with_rule": 10, "without_rule": 11})
        self.assertEqual([(h["pid"], h["status"], h["position_without"]) for h in r["hidden"]], [("H1", "not_confirmed", 3)])
        self.assertTrue(any(f["flag"] == "hides_above_median_rpv" and not f["confirmed"] for f in r["flags"]))
        self.assertEqual(r["verdict"], "hurts")  # unconfirmed: not yet "hides sellers"

    def test_presence_check_confirms_hidden_seller(self):
        _, out, _ = full("--presence-check", f"H1={FX / 'presence_empty.json'}")
        r = result(out, "900002")
        self.assertEqual(r["hidden"][0]["status"], "confirmed")
        self.assertEqual((r["verdict"], r["priority"]), ("hides sellers", "high"))
        self.assertEqual(out["results"][0]["priority"], "high")

    def test_presence_check_shows_it_was_only_deeper(self):
        _, out, _ = full("--presence-check", f"H1={FX / 'presence_found.json'}")
        self.assertEqual(result(out, "900002")["hidden"], [])

    def test_missing_rpv_is_missing_not_zero(self):
        _, out, _ = full()
        r = result(out, "all_algo")
        self.assertEqual(r["missing_rpv"], ["D"])
        self.assertEqual(r["rpv_coverage"], "0.50")
        self.assertEqual(r["estimated_effect"], "455.00")
        d = next(m for m in r["moves"] if m["pid"] == "D")
        self.assertIsNone(d["rpv"])
        self.assertEqual(out["rpv_not_found"], ["D"])

    def test_page_median_and_low_pins(self):
        _, out, _ = full()
        self.assertEqual(out["page_median_rpv"], "5.00")
        flag = next(f for f in result(out, "900001")["flags"] if f["flag"] == "pins_below_median_rpv")
        self.assertEqual(flag["pids"], ["X1", "X2"])

    def test_no_effect_and_unconfirmed_disable(self):
        _, out, _ = full()
        r = result(out, "950001")
        self.assertEqual(r["verdict"], "no visible effect")
        self.assertTrue(any("doesn't confirm" in w for w in r["warnings"]))

    def test_all_rules_lists_extra_rules_and_not_measured(self):
        _, out, _ = full()
        r = result(out, "all")
        self.assertEqual(r["rules_listed_only_when_off"], [{"id": "990001", "type": "algo"}])
        self.assertEqual(r["warnings"][:1], ["It may hide an above-median seller: confirm with a --presence-check grid before acting."])
        self.assertEqual(out["not_measured"], [{"id": "700001", "type": "facet"}])
        self.assertEqual(result(out, "all_algo")["rules_disabled"], ["800001"])

    def test_low_traffic(self):
        _, out, _ = full(query="query_perf_low.json")
        self.assertTrue(any("Low traffic" in w for w in out["warnings"]))
        # 950001 has no effect; all others are measured against 100 visits and $2,000
        self.assertEqual(result(out, "900001")["estimated_effect"], "-47.00")

    def test_neutral_band(self):
        _, out, _ = full(query="query_perf_big.json")  # -470 against $1,000,000 is inside neutral_band_share
        self.assertEqual(result(out, "900001")["verdict"], "neutral")

    def test_algo_helps_and_unmeasured_rules(self):
        code, out, _ = run("--baseline", FX / "baseline.json", "--toggled", f"all_algo={FX / 'off_all_algo.json'}",
                           "--query-perf", FX / "query_perf.json", "--query", "gown", "--page-size", "5",
                           "--product-rpv", FX / "rpv_table.json")
        self.assertEqual(code, 0)
        self.assertEqual(result(out, "all_algo")["verdict"], "helps")
        self.assertTrue(any("900001" in n for n in out["not_checked"]))

    def test_no_query_row_gives_unknown(self):
        _, out, _ = run("--baseline", FX / "baseline.json", "--toggled", f"900001={FX / 'off_900001.json'}",
                        "--query-perf", FX / "query_perf.json", "--query", "ballgown", "--page-size", "5",
                        "--product-rpv", FX / "rpv_table.json")
        r = result(out, "900001")
        self.assertEqual((r["verdict"], r["estimated_effect"]), ("unknown", None))
        self.assertTrue(any("matches 'ballgown' exactly" in n for n in out["not_checked"]))

    def test_never_outputs_debug_urls(self):
        _, out, _ = full()
        text = json.dumps(out)
        self.assertNotIn("auth_key", text)
        self.assertNotIn("FAKE", text)
        self.assertNotIn("sq.example.test", text)
        self.assertNotIn("search.example.test", text)

    def test_presence_check_for_other_pids_confirms_nothing(self):
        _, out, _ = full("--presence-check", f"Z9={FX / 'presence_empty.json'}")
        r = result(out, "900002")
        self.assertEqual(r["hidden"][0]["status"], "not_confirmed")
        self.assertEqual(r["verdict"], "hurts")

    def test_incomplete_presence_check_fails(self):
        code, out, _ = full("--presence-check", f"H1={FX / 'presence_incomplete.json'}")
        self.assertEqual(code, 1)
        self.assertIn("presence check holds 1 of 2", out["error"])

    def test_presence_check_needs_pids(self):
        code, out, _ = full("--presence-check", str(FX / "presence_empty.json"))
        self.assertEqual(code, 1)
        self.assertIn("PIDS=FILE", out["error"])

    def test_median_compares_exact_values(self):
        _, out, _ = full(rpv_table="rpv_table_4999.json")  # 4.999 would display as 5.00, the median
        flag = next(f for f in result(out, "900001")["flags"] if f["flag"] == "pins_below_median_rpv")
        self.assertEqual(flag["pids"], ["X1", "X2"])

    def test_mixed_currency_gives_no_estimates(self):
        _, out, _ = full("--product-rpv", f"D={FX / 'rpv_D_eur.json'}")
        self.assertTrue(out["mixed_currency"])
        self.assertTrue(any("different currencies" in w for w in out["warnings"]))
        self.assertIsNone(out["page_median_rpv"])
        for r in out["results"]:
            self.assertIsNone(r["estimated_effect"])
            self.assertIn(r["verdict"], ("unknown", "no visible effect"))

    def test_row_without_visits(self):
        _, out, _ = full(query="query_perf_novisits.json")
        self.assertTrue(any("no visits" in n for n in out["not_checked"]))
        self.assertIsNone(result(out, "900001")["estimated_effect"])

    def test_long_page_size_warns(self):
        _, out, _ = run("--baseline", FX / "baseline.json", "--query", "gown", "--page-size", "30")
        self.assertTrue(any("position_weights" in w and "page_size" in w for w in out["warnings"]))

    def test_query_file_round_trips_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            qf = Path(tmp) / "query.txt"
            q = 'gown $(x) `y` "z" \'w\''
            qf.write_text(q + "\n", encoding="utf-8", newline="")
            code, out, _ = run("--baseline", FX / "baseline.json", "--query-file", qf)
            self.assertEqual(code, 0)
            self.assertEqual(out["query"], q)
            qf.write_text("Gown\n", encoding="utf-8", newline="")
            _, out, _ = run("--baseline", FX / "baseline.json", "--toggled", f"900001={FX / 'off_900001.json'}",
                            "--query-perf", FX / "query_perf.json", "--query-file", qf, "--page-size", "5",
                            "--product-rpv", FX / "rpv_table.json")
            self.assertEqual(out["query_metrics"]["visits"], 1000)

    def test_exactly_one_query_option(self):
        code, out, _ = run("--baseline", FX / "baseline.json")
        self.assertEqual(code, 1)
        self.assertIn("exactly one of --query and --query-file", out["error"])
        with tempfile.TemporaryDirectory() as tmp:
            qf = Path(tmp) / "q.txt"
            qf.write_text("gown", encoding="utf-8")
            code, out, _ = run("--baseline", FX / "baseline.json", "--query", "gown", "--query-file", qf)
        self.assertEqual(code, 1)

    def test_error_text_is_redacted(self):
        code, out, _ = run("--baseline", FX / "error_email.json", "--query", "gown")
        self.assertEqual(code, 1)
        self.assertNotIn("ops@example.com", out["error"])
        self.assertNotIn("status.example.test", out["error"])
        self.assertIn("[email removed]", out["error"])

    def test_context_error_stops_and_is_not_echoed(self):
        code, out, _ = run("--baseline", FX / "denied.json", "--toggled", f"all={FX / 'off_all.json'}", "--query", "gown")
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertNotIn("not allowed", out["error"])

    def test_list_mode_says_what_to_toggle(self):
        code, out, _ = run("--baseline", FX / "baseline.json", "--query", "gown")
        self.assertEqual(code, 0)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["to_toggle"], {"one_at_a_time": ["900001", "900002", "950001"], "all_algo": ["800001"],
                                            "all": ["700001", "800001", "900001", "900002", "950001"]})

    def test_bad_toggled_spec(self):
        code, out, _ = run("--baseline", FX / "baseline.json", "--toggled", str(FX / "off_all.json"), "--query", "gown")
        self.assertEqual(code, 1)
        self.assertIn("NAME=FILE", out["error"])

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "impact.json"
            code, out, _ = full("--out", dest)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), out)

    def test_every_rules_key_has_a_note(self):
        keys = set(RULES) - {"about", "notes"}
        self.assertEqual(keys, set(RULES["notes"]))
        self.assertTrue(RULES["about"])

    def test_fixtures_end_with_newline(self):
        for p in FX.iterdir():
            self.assertTrue(p.read_bytes().endswith(b"\n"), p.name)


if __name__ == "__main__":
    unittest.main()
