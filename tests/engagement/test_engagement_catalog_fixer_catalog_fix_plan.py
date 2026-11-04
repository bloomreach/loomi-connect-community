"""Tests for engagement-catalog-fixer's catalog_fix_plan.py: plans built from catalog-parity-check findings and from
change files (full-record upserts, protected and undefined fields, stock words, deletes only when asked, batching
and v2 imports) and verify on the read-backs. All fixtures are synthetic."""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-catalog-fixer"
SCRIPT = SKILL / "scripts/catalog_fix_plan.py"
FX = ROOT / "tests/fixtures/engagement/engagement-catalog-fixer"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
CAT = "cat0000000000000000000001"
ITEMS = ("item_P100.json", "item_P200.json", "item_P300_search.json", "item_P400.json", "item_P500_not_found.json",
         "item_OLD1.json")
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")


def run(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


def plan(*extra, catalog=("catalog_v1.json",), items=ITEMS):
    """Run plan from an empty folder; return (summary printed, plan file)."""
    with tempfile.TemporaryDirectory() as tmp:
        args = ["plan", "--project-id", "proj-demo", "--project-name", "Demo project", "--catalog-id", CAT,
                "--out", "plan.json"]
        for c in catalog:
            args += ["--catalog", FX / c if not Path(str(c)).is_absolute() else c]
        for i in items:
            args += ["--items", FX / i if not Path(str(i)).is_absolute() else i]
        r = run(*args, *extra, cwd=tmp)
        assert r.returncode == 0, r.stdout + r.stderr
        written = sorted(p.name for p in Path(tmp).iterdir())
        assert written == ["plan.json"], written
        return json.loads(r.stdout), json.loads((Path(tmp) / "plan.json").read_text(encoding="utf-8"))


def by_target(p):
    return {c["target"]: c for c in p["changes"]}


def verify(plan_obj, *readbacks):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "plan.json").write_text(json.dumps(plan_obj), encoding="utf-8")
        args = ["verify", "--plan", "plan.json"]
        for n, f in readbacks:
            args += ["--readback", f"{n}={FX / f}"]
        return run(*args, cwd=tmp)


class FindingsPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary, cls.plan = plan("--findings", FX / "parity.json")
        cls.c = by_target(cls.plan)

    def test_shared_plan_shape(self):
        for k in ("ok", "project_id", "project_name", "catalog_id", "changes", "batches", "batch_calls", "counts"):
            self.assertIn(k, self.plan)
        self.assertNotIn("account", self.plan)
        for ch in self.plan["changes"]:
            for k in CHANGE_KEYS:
                self.assertIn(k, ch)
        self.assertEqual(self.plan["counts"], {"ready": 4, "blocked": 1, "no_change": 0})

    def test_upsert_sends_full_record_with_only_fixes_changed(self):
        ch = self.c["item P100"]
        self.assertEqual(ch["status"], "ready")
        self.assertEqual(ch["tool"], "upsert_catalog_item")
        before = json.loads((FX / "item_P100.json").read_text(encoding="utf-8"))["data"]["properties"]
        props = ch["payload"]["properties"]
        self.assertEqual(set(props), set(before))
        self.assertEqual(props["margin"], before["margin"])  # protected field kept unchanged
        self.assertEqual(ch["after"], {"availability": "Out Of Stock", "sale_price": 99})
        self.assertEqual(ch["before"], {"availability": "In Stock", "sale_price": 120})
        for k in set(props) - {"availability", "sale_price"}:
            self.assertEqual(props[k], before[k])
        self.assertEqual(ch["undo"][0]["tool"], "upsert_catalog_item")
        self.assertEqual(ch["undo"][0]["payload"]["properties"], before)
        self.assertEqual(ch["live_impact"], "live")

    def test_truncated_title_is_skipped_not_blocking(self):
        ch = self.c["item P100"]
        self.assertEqual([s["fix"] for s in ch["skipped"]], ["title"])
        self.assertEqual(ch["payload"]["properties"]["title"], "Trail Runner Shoe")

    def test_numeric_stock_goes_to_zero(self):
        ch = self.c["item P200"]
        self.assertEqual((ch["before"], ch["after"]), ({"stock_level": 12}, {"stock_level": 0}))

    def test_price_follows_catalog_number_type(self):
        self.assertEqual(self.c["item P300"]["after"], {"price": 15})

    def test_missing_item_is_blocked_never_created(self):
        ch = self.c["item P500"]
        self.assertEqual(ch["status"], "blocked")
        self.assertIsNone(ch["payload"])
        self.assertIn("not found", [p["check"] for p in ch["problems"]])

    def test_sparse_item_warns(self):
        ch = self.c["item P400"]
        self.assertEqual(ch["status"], "ready")
        self.assertIn("sparse item", [w["check"] for w in ch["warnings"]])

    def test_missing_products_not_planned_and_no_deletes(self):
        checks = sorted(x["check"] for x in self.plan["not_planned"])
        self.assertEqual(checks, ["missing_in_discovery", "missing_in_engagement"])
        self.assertFalse([c for c in self.plan["changes"] if c["kind"] == "delete"])

    def test_summary_has_no_payloads_or_protected_values(self):
        text = json.dumps(self.summary)
        self.assertNotIn("payload", text)
        self.assertNotIn("31.5", text)  # P100's margin
        self.assertNotIn("margin\": 12", text)

    def test_batches_and_calls(self):
        self.assertEqual(self.plan["batches"], [[1, 2, 3, 5]])
        calls = self.plan["batch_calls"][0]["calls"]
        self.assertEqual([c["tool"] for c in calls], ["upsert_catalog_item"] * 4)  # v1: never an import

    def test_truncated_listing_noted(self):
        self.assertTrue(any("larger --top" in n for n in self.plan["notes"]))


class ChangesAndDeletesTest(unittest.TestCase):
    def test_change_file_merges_with_findings_and_delete_is_its_own_batch(self):
        _, p = plan("--findings", FX / "parity.json", "--changes", FX / "changes.json")
        c = by_target(p)
        self.assertEqual(c["item P200"]["after"], {"price": 45, "stock_level": 0})
        d = c["item OLD1"]
        self.assertEqual((d["status"], d["kind"], d["tool"]), ("ready", "delete", "delete_catalog_item"))
        self.assertNotIn("margin", d["before"])
        self.assertEqual(d["protected_fields_hidden"], ["margin", "supplier_price"])
        self.assertEqual(d["undo"][0]["payload"]["properties"]["margin"], 5)  # the undo restores everything
        self.assertEqual(p["batches"][-1], [d["n"]])
        self.assertNotIn("missing_in_discovery", [x["check"] for x in p["not_planned"]])

    def test_delete_summary_shows_names_and_title_url_price_only(self):
        summary, _ = plan("--delete", "OLD1")
        before = summary["changes"][0]["before"]
        self.assertEqual(set(before), {"fields", "title", "url", "price"})
        self.assertNotIn("supplier_price", before["fields"])
        self.assertNotIn("margin", before["fields"])
        self.assertNotIn("Acme", json.dumps(summary))

    def test_url_must_be_https_and_host_change_warns(self):
        _, p = plan("--changes", FX / "changes_urls.json")
        c = by_target(p)
        self.assertEqual(c["item P200"]["status"], "blocked")
        self.assertEqual([x["check"] for x in c["item P200"]["problems"]], ["url"])
        self.assertEqual(c["item P300"]["status"], "ready")
        self.assertIn("host", [x["check"] for x in c["item P300"]["warnings"]])

    def test_delete_flag(self):
        _, p = plan("--delete", "OLD1")
        self.assertEqual([(c["kind"], c["status"]) for c in p["changes"]], [("delete", "ready")])

    def test_delete_of_missing_item_is_no_change(self):
        _, p = plan("--delete", "P500")
        self.assertEqual(p["changes"][0]["status"], "no_change")

    def test_blockers(self):
        _, p = plan("--changes", FX / "changes_bad.json")
        c = by_target(p)
        self.assertEqual([x["check"] for x in c["item P100"]["problems"]], ["protected"])
        self.assertEqual([x["check"] for x in c["item P200"]["problems"]], ["schema"])
        self.assertEqual([x["check"] for x in c["item P300"]["problems"]], ["delete"])
        self.assertEqual(p["batches"], [])

    def test_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "changes.json"
            f.write_text(json.dumps([{"action": "update", "item_id": "P200", "set": {"price": "50.00"}}]),
                         encoding="utf-8")
            _, p = plan("--changes", f)
        self.assertEqual(p["changes"][0]["status"], "no_change")

    def test_checks_filter(self):
        _, p = plan("--findings", FX / "parity.json", "--checks", "price_mismatch")
        self.assertEqual(sorted(c["target"] for c in p["changes"]), ["item P300", "item P500"])

    def test_engagement_key_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads((FX / "parity.json").read_text(encoding="utf-8"))
            data["id_mapping"] = "Discovery product ID (pid) = Engagement product_id, trimmed"
            f = Path(tmp) / "parity.json"
            f.write_text(json.dumps(data), encoding="utf-8")
            r = run("plan", "--project-id", "p", "--project-name", "P", "--catalog-id", CAT, "--catalog",
                    FX / "catalog_v1.json", "--findings", f, "--out", "plan.json", cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--engagement-key", r.stdout)

    def test_context_error_on_item_read_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("plan", "--project-id", "p", "--project-name", "P", "--catalog-id", CAT, "--catalog",
                    FX / "catalog_v1.json", "--items", FX / "error_project.json", "--delete", "OLD1",
                    "--out", "plan.json", cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("auth_key", r.stdout)
        self.assertNotIn("https://", r.stdout)


class V2ImportTest(unittest.TestCase):
    def test_large_v2_batch_uses_one_import_with_full_records(self):
        n = RULES["import_min_items"]
        with tempfile.TemporaryDirectory() as tmp:
            items, changes = [], []
            for i in range(n):
                f = Path(tmp) / f"item{i}.json"
                f.write_text(json.dumps({"success": True, "data": {"catalog_id": CAT, "_id": f"V{i}", "properties":
                             {"price": 10 + i, "title": f"Item {i}", "margin": 3}}}), encoding="utf-8")
                items.append(f)
                changes.append({"action": "update", "item_id": f"V{i}", "set": {"price": 5}})
            cf = Path(tmp) / "changes.json"
            cf.write_text(json.dumps(changes), encoding="utf-8")
            _, off = plan("--changes", cf, catalog=("catalog_v2.json", "catalog_v2_config.json"), items=items)
            _, p = plan("--changes", cf, "--use-import", catalog=("catalog_v2.json", "catalog_v2_config.json"),
                        items=items)
        self.assertFalse(RULES["use_import_for_v2"])
        self.assertEqual({c["tool"] for b in off["batch_calls"] for c in b["calls"]}, {"upsert_catalog_item"})
        self.assertEqual(p["catalog_version"], "v2")
        self.assertEqual(p["batches"][0], [1])  # the first import is one item, verified before the rest
        probe = p["batch_calls"][0]["calls"]
        self.assertEqual([c["tool"] for c in probe], ["import_catalog_items"])
        ops = probe[0]["payload"]["operations"]
        self.assertEqual(ops, [{"op": "upsert", "path": "/V0",
                                "value": {"fields": {"price": 5, "title": "Item 0", "margin": 3}}}])
        rest = p["batch_calls"][1]["calls"]
        expected = "import_catalog_items" if n - 1 >= RULES["import_min_items"] else "upsert_catalog_item"
        self.assertEqual({c["tool"] for c in rest}, {expected})


class VerifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.plan = plan("--findings", FX / "parity.json", "--changes", FX / "changes.json")
        cls.n = {c["target"]: c["n"] for c in cls.plan["changes"]}

    def results(self, *rb):
        r = verify(self.plan, *rb)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return {x["n"]: x for x in json.loads(r.stdout)["results"]}

    def test_in_place_and_gone(self):
        p100, old = self.n["item P100"], self.n["item OLD1"]
        res = self.results((p100, "readback_P100_ok.json"), (old, "readback_OLD1_gone.json"))
        self.assertEqual(res[p100]["state"], "in_place")
        self.assertEqual(res[old]["state"], "gone")

    def test_wiped_properties(self):
        p100 = self.n["item P100"]
        res = self.results((p100, "readback_P100_wiped.json"))[p100]
        self.assertEqual(res["state"], "not_in_place")
        self.assertIn("margin", res["wiped"])
        self.assertIn("alert", res)

    def test_old_values_suggest_reading_again(self):
        p100 = self.n["item P100"]
        res = self.results((p100, "readback_P100_old.json"))[p100]
        self.assertEqual(res["state"], "not_in_place")
        self.assertIn("Read it again", res["note"])

    def test_update_of_vanished_item_is_gone(self):
        # The read-back of OLD1's not-found doesn't name P100, so it's an error that stops verify.
        r = verify(self.plan, (self.n["item P100"], "readback_OLD1_gone.json"))
        self.assertEqual(r.returncode, 1)

    def test_empty_or_error_shaped_readback_is_not_gone(self):
        for f in ("readback_empty.json", "readback_is_error.json"):
            for target in ("item P100", "item OLD1"):
                r = verify(self.plan, (self.n[target], f))
                self.assertEqual(r.returncode, 1, (f, target, r.stdout))
                self.assertNotIn('"gone"', r.stdout)

    def test_context_errors_stop(self):
        for f in ("error_project.json", "error_rate_limited.json"):
            r = verify(self.plan, (self.n["item OLD1"], f))
            self.assertEqual(r.returncode, 1, f)
            self.assertNotIn("FAKEKEY", r.stdout)


PARITY = ROOT / "plugins/loomi-platform/skills/catalog-parity-check"


def load_script():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("catalog_fix_plan_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        self.assertIn("about", RULES)
        self.assertEqual(set(RULES) - {"about", "notes"}, set(RULES["notes"]))

    def test_shared_values_match_catalog_parity_check(self):
        parity = json.loads((PARITY / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(RULES["default_engagement_fields"]), set(parity["fields"]))
        for k, v in RULES["default_engagement_fields"].items():
            self.assertEqual(v, parity["fields"][k]["engagement"], k)
        self.assertEqual(RULES["id_case_insensitive"], parity["id_case_insensitive"])

    def test_truncation_matches_parity_display(self):
        src = (PARITY / "scripts/catalog_parity.py").read_text(encoding="utf-8")
        body = src[src.index("def display("):]
        body = body[:body.index("\ndef ", 1)]
        # display()'s last line cuts text values (URL, image, title); [:40] earlier is for non-numeric prices.
        cuts = re.findall(r"return str\(v\)\[:(\d+)\]", body)
        self.assertTrue(cuts, "catalog_parity.py display() no longer cuts text with return str(v)[:N]")
        self.assertEqual(int(cuts[-1]), RULES["truncated_value_chars"])

    def test_every_parity_stock_word_has_a_pair(self):
        parity = json.loads((PARITY / "references/rules.json").read_text(encoding="utf-8"))
        paired = {w for pair in RULES["stock_text_pairs"] for w in pair}
        for word in parity["in_stock_values"]:
            self.assertIn(word, paired, word)
        mod = load_script()
        for current, target, want in (("Low Stock", "out", "Out Of Stock"), ("preorder", "out", "out of stock"),
                                      ("limited availability", "out", "out of stock"),
                                      ("SOLD OUT", "in", "IN STOCK"), ("out of stock", "in", "in stock")):
            self.assertEqual(mod.stock_value(current, target, "availability", {}), (want, None), current)
        value, problem = mod.stock_value("discontinued", "in", "availability", {})
        self.assertIsNone(value)
        self.assertIn("isn't a stock word", problem)


if __name__ == "__main__":
    unittest.main()
