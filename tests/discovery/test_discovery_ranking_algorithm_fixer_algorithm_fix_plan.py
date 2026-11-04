"""Tests for discovery-ranking-algorithm-fixer's algorithm_fix_plan.py: turning ranking algorithm fixes (weight
changes, renames, corrected copies, deletes) into a plan file in the shared shape, and checking the writes with
verify. All fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-ranking-algorithm-fixer"
SCRIPT = SKILL / "scripts/algorithm_fix_plan.py"
FX = ROOT / "tests/fixtures/discovery/ranking_algorithm_fixer"
DETAILS = (1, 11, 12, 13, 14, 15, 16, 17, 21)
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")


def run(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


def plan_args(changes, out, review="review.json", experiments="experiments.json", rules=("7001",), extra=()):
    args = ["plan", "--changes", changes, "--algorithms", FX / "algos_keyword.json",
            "--algorithms", FX / "algos_category.json"]
    for i in DETAILS:
        args += ["--detail", FX / f"detail_{i}.json"]
    if review:
        args += ["--review", FX / review]
    for rid in rules:
        args += ["--rule", f"{rid}={FX / f'rule_{rid}.json'}"]
    if experiments:
        args += ["--experiments", FX / experiments]
    return args + ["--account", "acme_demo", "--environment", "staging", "--out", out, *extra]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, changes=None, **kw):
        if changes is None:
            path = FX / "changes.json"
        else:
            path = self.dir / "changes.json"
            path.write_text(json.dumps(changes), encoding="utf-8")
        r = run(*plan_args(path, self.dir / "plan.json", **kw), cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout), json.loads((self.dir / "plan.json").read_text(encoding="utf-8")), r.stdout

    def req(self, out, request):
        return next(c for c in out["changes"] if c["request"] == request)


class PlanShapeTest(Base):
    def test_shape_and_batches(self):
        out, full, _ = self.plan()
        self.assertTrue(out["ok"])
        for k in ("account", "environment", "site_group_id", "changes", "batches"):
            self.assertIn(k, out)
        for c in out["changes"]:
            for k in CHANGE_KEYS:
                self.assertIn(k, c)
            self.assertIn(c["status"], ("ready", "blocked", "no_change"))
            self.assertIn(c["live_impact"], ("none", "live"))
        self.assertEqual(out["counts"], {"ready": 5, "blocked": 7, "no_change": 0})
        # creates and renames together; each live weight change and each delete alone, deletes last
        self.assertEqual(out["batches"], [[6, 11], [1], [7], [2]])

    def test_required_context(self):
        r = run("plan", "--changes", FX / "changes.json", "--algorithms", FX / "algos_keyword.json",
                "--account", "acme_demo", "--out", self.dir / "p.json", cwd=self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--environment", r.stderr)

    def test_writes_only_out(self):
        self.plan()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["plan.json"])


class WeightTest(Base):
    def test_rebalance_before_after(self):
        out, full, _ = self.plan()
        c = self.req(out, 1)
        self.assertEqual((c["status"], c["kind"], c["live_impact"], c["tool"]),
                         ("ready", "update", "live", "update_ranking_algorithm"))
        rows = {r["signal"]: (r["before"], r["after"]) for r in c["signals"]}
        self.assertEqual(rows, {"raw_qd_revenue_keyword": (20.0, 30.0), "text_score_keyword": (50.0, 43.75),
                                "raw_qd_conversions_keyword": (20.0, 17.5), "raw_qd_views_keyword": (10.0, 8.75)})
        combined = full["changes"][0]["payload"]["model_metadata"]["combined"]
        self.assertEqual(sum(v["weight"] for v in combined.values()), 100)
        self.assertIn("text", full["changes"][0]["payload"]["model_metadata"])  # the whole model is sent back
        undo = full["changes"][0]["undo"][0]["payload"]["model_metadata"]["combined"]
        self.assertEqual(undo["raw_qd_revenue_keyword"]["weight"], 20)

    def test_rebalance_rounding_is_exact(self):
        out, full, _ = self.plan()
        combined = full["changes"][6]["payload"]["model_metadata"]["combined"]
        from decimal import Decimal
        self.assertEqual(sum(Decimal(repr(v["weight"])) for v in combined.values()), Decimal(100))

    def test_out_of_range_and_unknown(self):
        out, _, _ = self.plan([
            {"action": "update", "algorithm_id": 11, "weights": {"raw_qd_revenue_keyword": 150}},
            {"action": "update", "algorithm_id": 12, "weights": {"raw_qd_revenue_keyword": -1}},
            {"action": "update", "algorithm_id": 13, "weights": {"no_such_signal": 5}},
            {"action": "update", "algorithm_id": 17, "weights": {"unigram_product_name_tf": 0.2}},
            {"action": "update", "algorithm_id": 15, "weights": {"revenue": "40"}}])
        msgs = [" ".join(c["problems"]) for c in out["changes"]]
        self.assertIn("outside the allowed range", msgs[0])
        self.assertIn("outside the allowed range", msgs[1])
        self.assertIn("isn't a signal of this algorithm", msgs[2])
        self.assertIn("text-matching signal", msgs[3])
        self.assertIn("isn't a number", msgs[4])
        self.assertTrue(all(c["status"] == "blocked" for c in out["changes"]))

    def test_sum_must_be_total(self):
        out, _, _ = self.plan([{"action": "update", "algorithm_id": 11, "weights": {"raw_qd_revenue_keyword": 25}}])
        self.assertEqual(out["changes"][0]["status"], "blocked")
        self.assertIn("rebalance", out["changes"][0]["problems"][0])

    def test_high_traffic_needs_skip_test(self):
        out, _, _ = self.plan()
        self.assertIn("A/B test", self.req(out, 3)["problems"][0])
        ch = {"action": "update", "algorithm_id": 16, "weights": {"raw_qd_views_keyword": 15, "text_score_keyword": 45},
              "skip_test": True}
        out, _, _ = self.plan([ch])
        self.assertEqual(out["changes"][0]["status"], "ready")
        self.assertTrue(any("without an A/B test" in w for w in out["changes"][0]["warnings"]))

    def test_trained_abr_blocked(self):
        out, _, _ = self.plan()
        self.assertIn("ABR_MANUAL for good", self.req(out, 5)["problems"][0])

    def test_margin_warned_and_hidden(self):
        out, full, stdout = self.plan()
        c = self.req(out, 7)
        self.assertTrue(any("margin or cost-type" in w for w in c["warnings"]))
        self.assertTrue([r for r in c["signals"] if r["signal"] == "margin" and r["margin_or_cost"]])
        for value in ("12.5", "88.25"):
            self.assertNotIn(value, stdout)  # the catalog's margin range never reaches the screen
        self.assertEqual(full["changes"][6]["payload"]["model_metadata"]["combined"]["margin"]["min"], 12.5)

    def test_no_editor_emails(self):
        _, _, stdout = self.plan()
        self.assertNotIn("editor@example.com", stdout)
        self.assertNotIn("editor@example.com", (self.dir / "plan.json").read_text(encoding="utf-8"))

    def test_no_usage_blocks_weight_change(self):
        out, _, _ = self.plan([{"action": "update", "algorithm_id": 11, "weights": {"raw_qd_revenue_keyword": 30},
                                "rebalance": True}], review="review_empty.json")
        self.assertIn("No usage check", out["changes"][0]["problems"][0])


class CreateDeleteTest(Base):
    def test_abr_copy(self):
        out, full, _ = self.plan()
        c = self.req(out, 6)
        self.assertEqual((c["status"], c["tool"], c["live_impact"]), ("ready", "create_abr_algorithm", "none"))
        p = c["payload"]
        self.assertEqual((p["type"], p["base_algo_id"], p["search_type"]), ("ABR_MANUAL", "br-ddd14444", "CATEGORY"))
        self.assertEqual(c["undo"][0]["tool"], "delete_ranking_algorithm")
        self.assertEqual(c["undo"][0]["payload"]["algorithm_id"], f"<id returned by change {c['n']}>")

    def test_legacy_copy_and_limits(self):
        out, _, _ = self.plan([{"action": "create", "copy_of": 21, "name": "Margin cat v2",
                                "weights": {"margin": 10}, "rebalance": True}])
        c = out["changes"][0]
        self.assertEqual((c["status"], c["tool"], c["payload"]["type"]), ("ready", "create_ranking_algorithm", "MANUAL"))
        self.assertEqual(c["payload"]["domain_key"], "acme_shop")
        out, _, _ = self.plan()
        self.assertIn("custom keyword algorithms", self.req(out, 9)["problems"][0])

    def test_name_clash(self):
        out, _, _ = self.plan()
        self.assertIn("already has the name", self.req(out, 10)["problems"][0])

    def test_delete_unused_and_undo(self):
        out, full, _ = self.plan()
        c = self.req(out, 2)
        self.assertEqual((c["status"], c["kind"], c["tool"]), ("ready", "delete", "delete_ranking_algorithm"))
        self.assertEqual(c["payload"]["family"], "legacy")
        undo = full["changes"][1]["undo"][0]
        self.assertEqual((undo["tool"], undo["payload"]["type"]), ("create_ranking_algorithm", "MANUAL"))
        self.assertIn("definition", c["before"])

    def test_delete_guards(self):
        out, _, _ = self.plan()
        self.assertTrue(any("Experiment 'Algo test'" in p for p in self.req(out, 4)["problems"]))
        default = " ".join(self.req(out, 8)["problems"])
        self.assertIn("default algorithm", default)
        self.assertIn("Bloomreach's own rankers", default)
        self.assertIn("one change per algorithm", self.req(out, 12)["problems"][0])

    def test_delete_seen_in_grid_or_rule(self):
        out, _, _ = self.plan([{"action": "delete", "algorithm_id": 12}], rules=("7001", "7009"))
        self.assertIn("rule 7009", out["changes"][0]["problems"][0])
        r = run(*plan_args(FX / "changes.json", self.dir / "p.json", extra=("--grid", FX / "grid_q_hats.json")),
                cwd=self.dir)
        out = json.loads(r.stdout)
        self.assertEqual(self.req(out, 2)["status"], "blocked")
        self.assertIn("rule 801", self.req(out, 2)["problems"][0])

    def test_abr_delete_undo(self):
        out, _, _ = self.plan([{"action": "delete", "algorithm_id": 15}])
        c = out["changes"][0]
        self.assertEqual((c["status"], c["payload"]["family"], c["undo"][0]["tool"]),
                         ("ready", "abr", "create_abr_algorithm"))
        out, _, _ = self.plan([{"action": "delete", "algorithm_id": 14}])
        self.assertEqual(out["changes"][0]["undo"], [])
        self.assertIn("Ranking Studio", out["changes"][0]["undo_note"])

    def test_unread_experiment_rule_blocks(self):
        out, _, _ = self.plan([{"action": "delete", "algorithm_id": 12}], experiments="experiments_unread.json")
        self.assertIn("wasn't read", out["changes"][0]["problems"][0])

    def test_missing_experiments_fails(self):
        r = run(*plan_args(FX / "changes.json", self.dir / "p.json", experiments=None), cwd=self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--experiments", r.stdout)

    def test_rename_needs_no_experiments(self):
        out, _, _ = self.plan([{"action": "update", "algorithm_id": 15, "name": "Manual ABR 2026"}], experiments=None)
        self.assertEqual((out["changes"][0]["status"], out["changes"][0]["live_impact"]), ("ready", "none"))


class VerifyTest(Base):
    def verify(self, *pairs):
        self.plan()
        args = ["verify", "--plan", self.dir / "plan.json"]
        for n, f in pairs:
            args += ["--readback", f"{n}={FX / f}"]
        return run(*args, cwd=self.dir)

    def test_update_create_delete(self):
        r = self.verify((1, "readback_11_ok.json"), (6, "readback_create_ok.json"), (2, "readback_404_12.txt"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        res = {x["n"]: x for x in out["results"]}
        self.assertEqual(res[1]["result"], "in_place")
        self.assertEqual(res[1]["status"], "Syncing")
        self.assertEqual((res[6]["result"], res[6]["algorithm_id"]), ("in_place", 31))
        self.assertEqual(res[2]["result"], "gone")
        self.assertTrue(out["all_match"])
        self.assertEqual(out["not_checked"], [7, 11])
        self.assertNotIn("search.example.test", r.stdout)

    def test_not_in_place(self):
        out = json.loads(self.verify((1, "readback_11_unchanged.json"), (2, "readback_12_exists.json")).stdout)
        self.assertEqual([x["result"] for x in out["results"]], ["not_in_place", "not_in_place"])
        self.assertIn("weight raw_qd_revenue_keyword", out["results"][0]["detail"])

    def test_soft_deleted_record_is_gone(self):
        out = json.loads(self.verify((2, "readback_12_deleted.json")).stdout)
        self.assertEqual(out["results"][0]["result"], "gone")

    def test_other_not_found_stops(self):
        r = self.verify((2, "readback_404_other.txt"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("doesn't say algorithm 12 is missing", r.stdout)
        self.assertNotIn("search.example.test", r.stdout)

    def test_context_error_stops(self):
        r = self.verify((2, "readback_denied.json"))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("acme_demo", r.stdout)


class RulesFileTest(unittest.TestCase):
    def test_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertTrue(rules["about"])
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
