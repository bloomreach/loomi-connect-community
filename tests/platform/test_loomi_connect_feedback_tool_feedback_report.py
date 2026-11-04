"""Tests for loomi-connect-feedback's tool_feedback_report.py: listing the (bug?) items, building and linting one
submit_llm_feedback report (placeholders, blockers, length limits, the plan shape in docs/skill-authoring.md), and
reading the tool's response. All fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-platform/skills/loomi-connect-feedback"
SCRIPT = SKILL / "scripts/tool_feedback_report.py"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
FX = ROOT / "tests/fixtures/platform/loomi-connect-feedback"
DOC = FX / "known-tool-behaviour.md"
TOOLS = FX / "published-tools.txt"
GOOD = json.loads((FX / "report_good.json").read_text(encoding="utf-8"))
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")


def run(*args, cwd=None):
    """Run the script by its full path, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=cwd or tmp)
        if cwd is None:
            assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def ok(r):
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def build(report, *extra, env="production"):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "report.json"
        p.write_text(json.dumps(report), encoding="utf-8")
        return ok(run("build", "--report", p, "--environment", env, "--known-doc", DOC, "--published-tools", TOOLS,
                      *extra))


def with_(**kw):
    d = json.loads(json.dumps(GOOD))
    d.update(kw)
    return d


def checks(out):
    return sorted({p["check"] for p in out["changes"][0]["problems"]})


class ListKnown(unittest.TestCase):
    def test_lists_marked_items_with_tools_sections_and_links(self):
        out = ok(run("list-known", "--doc", DOC, "--published-tools", TOOLS))
        self.assertEqual([i["line"] for i in out["items"]], [10, 12, 17])
        first = out["items"][0]
        self.assertEqual(first["section"], "Discovery")
        self.assertEqual(first["subsection"], "Query performance")
        self.assertEqual(first["tools"], ["get_discovery_category_performance_table"])
        self.assertTrue(first["link"].endswith("known-tool-behaviour.md#L10"))
        self.assertTrue(first["link"].startswith(RULES["repo_doc_url"]))
        # no tool on the line: falls back to the tool in the subsection heading
        self.assertEqual(out["items"][1]["tools"], ["get_discovery_query_performance"])
        # nested bullet: the parent bullet gives the tool
        nested = out["items"][2]
        self.assertEqual(nested["tools"], ["create_email_campaign"])
        self.assertIn("always creates a draft", nested["parent"])
        self.assertFalse(any(i["already_sent"] for i in out["items"]))

    def test_repo_doc_parses(self):
        out = ok(run("list-known", "--doc", ROOT / "docs/known-tool-behaviour.md",
                     "--published-tools", ROOT / "docs/published-tools.txt"))
        self.assertGreater(out["count"], 0)
        for item in out["items"]:
            self.assertIn(RULES["known_marker"], item["text"] + (item["parent"] or ""))


class Build(unittest.TestCase):
    def test_good_report_is_ready_with_plan_shape(self):
        out = build(GOOD)
        self.assertTrue(out["ok"])
        self.assertEqual(out["environment"], "production")
        ch = out["changes"][0]
        for k in CHANGE_KEYS:
            self.assertIn(k, ch)
        self.assertEqual(ch["status"], "ready", ch["problems"])
        self.assertEqual((ch["kind"], ch["tool"], ch["live_impact"]), ("create", "submit_llm_feedback", "none"))
        self.assertEqual(ch["undo"], [])
        self.assertEqual(out["batches"], [[1]])
        self.assertEqual(len(out["changes"]), 1)

    def test_payload_matches_tool_schema(self):
        p = build(GOOD)["changes"][0]["payload"]
        self.assertTrue(set(p) <= {"gap_type", "what_i_tried", "feedback", "completion_estimate", "client", "model"})
        self.assertIn(p["gap_type"], RULES["gap_types"])
        self.assertEqual(p["completion_estimate"], 3)
        self.assertLessEqual(len(p["feedback"]), RULES["max_field_chars"])

    def test_arguments_and_excerpt_get_placeholders(self):
        fb = build(GOOD)["changes"][0]["payload"]["feedback"]
        for leaked in ("9999", "FAKEauthkey123", "demo_store_test", "shop.demo.test", "ops@example.com",
                       "5f2b9c8e1a4d7f3b6c0e9a21", "FAKEsecret999", "123e4567-e89b-12d3-a456-426614174000",
                       "api.demo.test"):
            self.assertNotIn(leaked, fb)
        for ph in ('"account_id": "<account_id>"', '"auth_key": "<auth_key>"', '"domain_key": "<domain_key>"',
                   '"page_url": "<page_url>"', "<email>", "<url>", "<id>"):
            self.assertIn(ph, fb)
        self.assertIn('"days": 30', fb)
        self.assertIn('"filter_preset": "lowest_converting"', fb)

    def test_feedback_has_every_section(self):
        fb = build(GOOD)["changes"][0]["payload"]["feedback"]
        self.assertTrue(fb.startswith(RULES["report_prefix"] + " get_discovery_category_performance_table: "))
        for part in ("Environment: production", "Client: claude-code", "Expected: ", "Actual: ",
                     "Minimal reproduction", "  tool: get_discovery_category_performance_table",
                     RULES["repo_doc_url"] + "#L10", "Suggestion: "):
            self.assertIn(part, fb)

    def test_leaky_free_text_is_blocked_without_repeating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = ok(run("build", "--report", FX / "report_leaky.json", "--environment", "production",
                         "--private-terms", FX / "private-terms.txt", cwd=tmp))
        self.assertEqual(out["changes"][0]["status"], "blocked")
        self.assertEqual(out["batches"], [])
        self.assertEqual(checks(out), ["email", "id", "phone", "private_term", "secret", "url"])
        shown = json.dumps(out["changes"][0]["problems"])
        for secret in ("jane.doe@example.com", "FAKEtok", "FAKEkey1", "FAKEbearertoken12345", "Acme Outdoor"):
            self.assertNotIn(secret, shown)

    def test_private_terms_in_arguments_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            terms = Path(tmp) / "terms.txt"
            terms.write_text("Demo Brand\n", encoding="utf-8")
            out = build(with_(arguments={"q": "demo brand jackets"}), "--private-terms", terms)
        self.assertEqual(out["changes"][0]["status"], "ready")
        self.assertIn('"q": "<name> jackets"', out["changes"][0]["payload"]["feedback"])

    def test_list_of_reports_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reports.json"
            p.write_text(json.dumps([GOOD, GOOD]), encoding="utf-8")
            r = run("build", "--report", p, "--environment", "production")
        self.assertEqual(r.returncode, 1)
        self.assertIn("One report per plan", json.loads(r.stdout)["error"])

    def test_environment_is_required(self):
        r = run("build", "--report", FX / "report_good.json")
        self.assertNotEqual(r.returncode, 0)

    def test_schema_violations_block(self):
        self.assertIn("gap_type", checks(build(with_(gap_type="BUG"))))
        self.assertIn("completion_estimate", checks(build(with_(completion_estimate=9))))
        self.assertIn("completion_estimate", checks(build(with_(completion_estimate=True))))
        self.assertIn("summary", checks(build(with_(summary="two\nlines"))))
        self.assertIn("summary", checks(build(with_(summary="x" * (RULES["summary_max_chars"] + 1)))))
        self.assertIn("tool", checks(build(with_(tool="Bad Tool"))))
        self.assertIn("actual", checks(build(with_(actual=""))))
        self.assertIn("length", checks(build(with_(client="c" * (RULES["max_short_field_chars"] + 1)))))

    def test_over_length_blocks(self):
        long_excerpt = "rows: [] " * (RULES["max_field_chars"] // 8)
        out = build(with_(response_excerpt=long_excerpt))
        self.assertIn("length", checks(out))
        self.assertGreater(out["summary"]["feedback_chars"], RULES["max_field_chars"])

    def test_known_line_must_be_marked(self):
        self.assertIn("known_line", checks(build(with_(known_line=11))))
        self.assertIn("known_line", checks(build(with_(known_line=999))))

    def test_warnings(self):
        out = build(with_(completion_estimate=RULES["completion_estimate_max"], tool="get_unknown_thing",
                          known_line=17), env="staging")
        self.assertEqual(out["changes"][0]["status"], "ready")
        warned = sorted(w["check"] for w in out["changes"][0]["warnings"])
        self.assertEqual(warned, ["completion_estimate", "known_line", "tool"])
        eng = build(with_(product="engagement"), env="staging")
        self.assertIn("environment", [w["check"] for w in eng["changes"][0]["warnings"]])

    def test_default_what_i_tried(self):
        report = with_()
        del report["what_i_tried"]
        p = build(report)["changes"][0]["payload"]
        self.assertIn("get_discovery_category_performance_table", p["what_i_tried"])

    def test_deterministic(self):
        self.assertEqual(build(GOOD), build(GOOD))


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.plan = self.dir / "plan.json"
        self.log = self.dir / "sent.jsonl"
        ok(run("build", "--report", FX / "report_good.json", "--environment", "production", "--known-doc", DOC,
               "--out", self.plan, cwd=self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self, name):
        out = ok(run("verify", "--plan", self.plan, "--response", f"1={FX / name}", "--sent-log", self.log,
                     cwd=self.dir))
        self.assertIn("no published tool to read", out["read_back"])
        return out["results"][0]

    def test_accepted_with_id(self):
        res = self.verify("response_ok.json")
        self.assertEqual((res["state"], res["feedback_id"]), ("accepted", "fb-0001"))

    def test_rejections(self):
        rate = self.verify("response_rate.json")
        self.assertEqual((rate["state"], rate["reason"], rate["stop"]), ("rejected", "rate_limited", True))
        invalid = self.verify("response_invalid.json")
        self.assertEqual((invalid["state"], invalid["reason"], invalid["stop"]), ("rejected", "invalid", False))
        access = self.verify("response_access.json")
        self.assertEqual((access["state"], access["reason"], access["stop"]), ("rejected", "context", True))
        self.assertFalse(self.log.exists(), "rejected reports must not be logged as sent")

    def test_unclear_is_unknown_and_redacted(self):
        res = self.verify("response_unclear.json")
        self.assertEqual(res["state"], "unknown")
        self.assertNotIn("internal.demo.test", res["error"])
        self.assertEqual(self.verify("response_bare.json")["state"], "unknown")

    def test_sent_log_blocks_resend_and_marks_list(self):
        self.verify("response_unclear.json")
        out = ok(run("build", "--report", FX / "report_good.json", "--environment", "production", "--known-doc",
                     DOC, "--sent-log", self.log, cwd=self.dir))
        self.assertEqual(checks(out), ["already_sent"])
        listed = ok(run("list-known", "--doc", DOC, "--sent-log", self.log, cwd=self.dir))
        self.assertEqual([i["line"] for i in listed["items"] if i["already_sent"]], [10])

    def test_unready_change_refused(self):
        r = run("verify", "--plan", self.plan, "--response", f"2={FX / 'response_ok.json'}", cwd=self.dir)
        self.assertEqual(r.returncode, 1)


class Rules(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        keys = set(RULES) - {"about", "notes"}
        self.assertEqual(sorted(keys - set(RULES["notes"])), [])
        self.assertEqual(sorted(set(RULES["notes"]) - keys), [])
        self.assertTrue(RULES["about"])


if __name__ == "__main__":
    unittest.main()
