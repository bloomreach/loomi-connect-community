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
        if "--private-terms" not in extra:
            extra = ("--private-terms", FX / "private-terms.txt", *extra)
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
        for ph in ('"account_id": "<accountid>"', '"auth_key": "<authkey>"', '"domain_key": "<domainkey>"',
                   '"page_url": "<pageurl>"', '"note": "<note>"', '"debug": "<debug>"', '"request_id": "<requestid>"'):
            self.assertIn(ph, fb)
        self.assertIn('"days": 30', fb)
        self.assertIn('"filter_preset": "lowest_converting"', fb)

    def test_feedback_has_every_section(self):
        fb = build(GOOD)["changes"][0]["payload"]["feedback"]
        self.assertTrue(fb.startswith(RULES["report_prefix"] + " get_discovery_category_performance_table: "))
        for part in ("Environment: production", "Expected: ", "Actual: ",
                     "Minimal reproduction", "  tool: get_discovery_category_performance_table",
                     RULES["repo_doc_url"] + "#L10", "Suggestion: "):
            self.assertIn(part, fb)

    def test_leaky_free_text_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = ok(run("build", "--report", FX / "report_leaky.json", "--environment", "production",
                         "--private-terms", FX / "private-terms.txt", cwd=tmp))
        sent = json.dumps(out["changes"][0]["payload"])
        for secret in ("jane.doe@example.com", "FAKEtok", "FAKEkey1", "FAKEbearertoken12345", "Acme Outdoor",
                       "5f2b9c8e1a4d7f3b6c0e9a21", "app.demo.test", "7946"):
            self.assertNotIn(secret, sent)
        self.assertIn("redacted", [w["check"] for w in out["changes"][0]["warnings"]])

    def test_private_terms_in_arguments_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            terms = Path(tmp) / "terms.txt"
            terms.write_text("Demo Brand\n", encoding="utf-8")
            out = build(with_(arguments={"q": "demo brand jackets"}), "--private-terms", terms)
        self.assertEqual(out["changes"][0]["status"], "ready")
        self.assertIn('"q": "<q>"', out["changes"][0]["payload"]["feedback"])

    def test_list_of_reports_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reports.json"
            p.write_text(json.dumps([GOOD, GOOD]), encoding="utf-8")
            r = run("build", "--report", p, "--environment", "production", "--private-terms", FX / "private-terms.txt")
        self.assertEqual(r.returncode, 1)
        self.assertIn("One report per plan", json.loads(r.stdout)["error"])

    def test_environment_is_required(self):
        r = run("build", "--report", FX / "report_good.json", "--private-terms", FX / "private-terms.txt")
        self.assertNotEqual(r.returncode, 0)

    def test_private_terms_file_is_required(self):
        r = run("build", "--report", FX / "report_good.json", "--environment", "production")
        self.assertNotEqual(r.returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "terms.txt"
            empty.write_text("", encoding="utf-8")
            out = build(GOOD, "--private-terms", empty)
            self.assertIn("private_terms", checks(out))
            empty.write_text(RULES["private_terms_none_line"] + "\n", encoding="utf-8")
            out = build(GOOD, "--private-terms", empty)
        self.assertEqual(out["changes"][0]["status"], "ready", out["changes"][0]["problems"])

    def test_schema_violations_block(self):
        self.assertIn("gap_type", checks(build(with_(gap_type="BUG"))))
        self.assertIn("completion_estimate", checks(build(with_(completion_estimate=9))))
        self.assertIn("completion_estimate", checks(build(with_(completion_estimate=True))))
        self.assertIn("summary", checks(build(with_(summary="two\nlines"))))
        self.assertIn("summary", checks(build(with_(summary="x" * (RULES["summary_max_chars"] + 1)))))
        self.assertIn("tool", checks(build(with_(tool="Bad Tool"))))
        self.assertIn("actual", checks(build(with_(actual=""))))

    def test_over_length_blocks(self):
        long_excerpt = "rows: [] " * (RULES["max_field_chars"] // 8)
        out = build(with_(response_excerpt=long_excerpt))
        self.assertIn("length", checks(out))
        self.assertGreater(out["summary"]["feedback_chars"], RULES["max_field_chars"])

    def test_known_line_must_be_marked(self):
        self.assertIn("known_line", checks(build(with_(known_line=11))))
        self.assertIn("known_line", checks(build(with_(known_line=999))))

    def test_warnings(self):
        out = build(with_(completion_estimate=RULES["completion_estimate_max"], tool="search_scenarios",
                          known_line=17), env="staging")
        self.assertEqual(out["changes"][0]["status"], "ready", out["changes"][0]["problems"])
        warned = sorted(w["check"] for w in out["changes"][0]["warnings"] if not w.get("soft"))
        self.assertEqual(warned, ["completion_estimate", "known_line", "redacted"])
        self.assertIn("tool", checks(build(with_(tool="get_unknown_thing"))))
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
               "--private-terms", FX / "private-terms.txt", "--out", self.plan, cwd=self.dir))

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
                     DOC, "--private-terms", FX / "private-terms.txt", "--sent-log", self.log, cwd=self.dir))
        self.assertEqual(checks(out), ["already_sent"])
        listed = ok(run("list-known", "--doc", DOC, "--sent-log", self.log, cwd=self.dir))
        self.assertEqual([i["line"] for i in listed["items"] if i["already_sent"]], [10])

    def test_unready_change_refused(self):
        r = run("verify", "--plan", self.plan, "--response", f"2={FX / 'response_ok.json'}", cwd=self.dir)
        self.assertEqual(r.returncode, 1)


REVIEW_LEAKS = ("acme-demo.test", "acme-shop", "6012345", "6013", "6012", "eyJhbGci", "FAKEsig", "Jane", "Doe",
                "acme_demo_test", "FAKEaccess9token", "FAKEclientsecret", "AKIAFAKE", "7946", "0958", "555-123",
                "203.0.113.7", "size 12 dress", "Acme", "acme-prod", "FAKEauthkey", "VIP", "RkFLRTpGQUtF",
                "FAKEbearer", "abcdef12", "FAKEgoogle", "FAKEopenai", "GOCSPX-FAKE", "xoxb-FAKE", "ghp_FAKE",
                "glpat-FAKE", "FAKEapikey123", "FAKErefresh", "98765")


class SecurityReview(unittest.TestCase):
    """The security review's synthetic report: every item must be redacted or the plan blocked."""

    def payload_text(self, out):
        return json.dumps(out["changes"][0]["payload"], ensure_ascii=False)

    def test_review_report_never_ready_with_a_leak(self):
        out = build(json.loads((FX / "report_review.json").read_text(encoding="utf-8")),
                    "--private-terms", FX / "private-terms-review.txt")
        ch = out["changes"][0]
        text = self.payload_text(out)
        leaks = [x for x in REVIEW_LEAKS if x in text]
        self.assertTrue(ch["status"] == "blocked" or not leaks, leaks)
        self.assertEqual(leaks, [], "redaction should catch every item in the review report")

    def test_allow_list_keeps_only_plain_enum_values_numbers_and_dates(self):
        args = json.loads((FX / "report_review.json").read_text(encoding="utf-8"))["arguments"]
        out = build(with_(arguments=args), "--private-terms", FX / "private-terms-review.txt")
        fb = out["changes"][0]["payload"]["feedback"]
        for kept in ('"filter_preset": "lowest_converting"', '"search_by": "query"', '"rows": 24',
                     '"start_date": "2026-10-01"', '"fl": "pid,brand"', '"sort": "price desc"'):
            self.assertIn(kept, fb)
        for ph in ('"accountId": "<accountid>"', '"account_id": "<accountid>"', '"campaign_name": "<campaignname>"',
                   '"segment": "<segment>"', '"query": "<query>"', '"search_query": "<searchquery>"', '"q": "<q>"',
                   '"name": "<name>"'):
            self.assertIn(ph, fb)


def load_module():
    import importlib.util
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("tool_feedback_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Patterns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def red(self, text):
        return self.m.redact_text(text)

    def test_each_free_text_pattern(self):
        cases = {
            "see shop.acme.test/search?account_id=1": "acme",
            "see www.acme-shop.com/p/1": "acme",
            "img //cdn.acme.test/a.png": "cdn.",
            "host www.acme-shop.com only": "acme",
            "mail ops@example.com": "ops@",
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJGQUtFIn0.FAKEsig": "eyJ",
            "Authorization: Basic RkFLRTpGQUtF": "RkFL",
            "Bearer FAKEbearer": "FAKEbearer",
            "X-Api-Key: FAKEheadervalue": "FAKEheader",
            "api-key: FAKEapikey": "FAKEapikey",
            "refresh_token=FAKErefresh": "FAKErefresh",
            "token: abcdef12": "abcdef12",
            '"client_secret": "FAKEcs"': "FAKEcs",
            "key AKIAFAKE00FAKE00FAKE0": "AKIA",
            "g ya29.FAKEgoogle": "ya29",
            "o sk-FAKEopenai123": "sk-FAKE",
            "c GOCSPX-FAKE": "GOCSPX",
            "s xoxb-FAKE": "xoxb",
            "gh ghp_FAKEgithub": "ghp_",
            "gl glpat-FAKEgitlab": "glpat",
            "from 203.0.113.7": "203.0",
            "call 020 7946 0958": "7946",
            "call 555-123-4567": "4567",
            "call +44 20 7946 0000": "7946",
            "account 6012345 project acme-prod": "6012345",
            "project acme-prod": "acme-prod",
            "id 6413": "6413",
            "row 123456": "123456",
            "User Jane Doe failed": "Jane",
            "created by Jane Doe": "Jane",
            '"lastModifiedBy": "Jane Doe"': "Jane",
            "uuid 123e4567-e89b-12d3-a456-426614174000": "123e4567",
            "hex 5f2b9c8e1a4d7f3b6c0e9a21": "5f2b",
        }
        for text, leak in cases.items():
            self.assertNotIn(leak, self.red(text), text)

    def test_ordinary_text_survives(self):
        for text in ("filter_preset=lowest_converting returns 0 rows on 2026-11-04",
                     "days 7 and 30, page 2, total_rows 0",
                     "data.debug.request.experiments holds the list",
                     "https://github.com/bloomreach/loomi-connect-community/blob/main/docs/known-tool-behaviour.md#L10",
                     "$11.07M against $19.94M"):
            self.assertEqual(self.red(text), text)

    def test_names_are_normalised(self):
        self.assertEqual(self.m.nk("account_Id"), self.m.nk("accountId"))
        self.assertTrue(self.m.sensitive("accountId"))
        self.assertTrue(self.m.sensitive("lastModifiedBy"))
        self.assertTrue(self.m.sensitive("X-Api-Key"))
        self.assertFalse(self.m.sensitive("filter_preset"))

    def test_stricter_lint_catches_what_redaction_misses(self):
        for text in ("user@host.example", "abcdEFGH1234ijklMNOP5678qrst", "see ?account=1", "www.shop",
                     "number 1234567"):
            self.assertTrue(self.m.lint_text("x", text, [])[0], text)
        self.assertEqual(self.m.lint_text("x", "filter_preset returned <id> rows", []), ([], []))

    def test_excerpt_json_uses_allow_list_and_keeps_error_text(self):
        out = self.m.redact_excerpt(json.dumps({"error": "User Jane Doe denied", "owner": "Jane Doe",
                                                "count": 3, "rows": [{"title": "Jane's dress"}]}), [])
        self.assertNotIn("Jane", out)
        self.assertIn('"count": 3', out)
        self.assertIn("denied", out)


class Round3(unittest.TestCase):
    """The third audit: the final strings are linted as sent, hard leaks block, soft ones warn."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def hard(self, text, terms=()):
        return [h["check"] for h in self.m.lint_text("feedback", text, self.m.term_patterns(list(terms)))[0]]

    def soft(self, text):
        return [h["check"] for h in self.m.lint_text("feedback", text, [])[1]]

    def test_s1_payload_preview_has_every_field_verbatim(self):
        out = build(with_(model="model-x"))
        p, prev = out["changes"][0]["payload"], out["payload_preview"]
        for k in ("gap_type", "completion_estimate"):
            self.assertIn(f"{k}: {p[k]}", prev)
        self.assertIn("client: (never sent", prev)
        self.assertIn("model: (never sent", prev)
        self.assertIn(p["feedback"], prev)
        self.assertIn(p["what_i_tried"], prev)

    def test_s2_nfkc_and_invisible_characters(self):
        self.assertNotIn("example", self.m.redact_text("jane＠example.com"))
        self.assertNotIn("acme", self.m.redact_text("shop.ac​me.com/p"))
        self.assertIn("email", self.hard(self.m.clean_str("a＠b")))
        out = build(with_(summary="Problem for Ac‍me Outdoor"),
                    "--private-terms", FX / "private-terms-review.txt")
        self.assertNotIn("Acme", out["changes"][0]["payload"]["feedback"])

    def test_s3_known_text_and_tool_are_linted_as_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "known.md"
            doc.write_text("## Discovery\n\n- `search_scenarios` leaks for ops@example.com. **(bug?)**\n",
                           encoding="utf-8")
            report = with_(tool="search_scenarios", known_line=3)
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(report), encoding="utf-8")
            out = ok(run("build", "--report", p, "--environment", "production", "--known-doc", doc,
                         "--private-terms", FX / "private-terms.txt", cwd=tmp))
        self.assertNotIn("ops@example.com", out["changes"][0]["payload"]["feedback"])
        terms = Path(FX / "private-terms.txt")
        self.assertIn("private_term", checks(build(with_(tool="search_scenarios"), "--private-terms",
                                                   self.write_terms("search scenarios"))))
        self.assertTrue(terms.exists())

    def write_terms(self, *terms):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [f.unlink() for f in d.iterdir()] and None or d.rmdir())
        f = d / "terms.txt"
        f.write_text("\n".join(terms) + "\n", encoding="utf-8")
        return f

    def test_s4_hard_blocks(self):
        cases = {
            "contact a@b": "email", "jane (at) example": "email", "jane at example dot com": "email",
            "see https://evil.example/x": "url", "go to shop.acme.com.br now": "host", "[here](shop.acme.io)": "url",
            "token: abcdef12": "secret", "sk_live_FAKE51abc": "secret", "Cookie: sid=FAKE": "cookie",
            "_session=FAKEsess1": "secret", "sig a%3Db%3D": "secret", "id 5f2b9c8e1a4d7f3b6c0e9a21": "id",
            "from 2001:db8::1": "ip", "card 4111 1111 1111 1111": "card", "iban GB82WEST12345698765432": "iban",
            "from 203.0.113.7": "ip", "secret aB3/dE5+fG7=hI9kL1": "secret",
        }
        for text, check in cases.items():
            self.assertIn(check, self.hard(text), text)

    def test_s4_soft_warnings_dont_block(self):
        for text, check in (("I asked Jane Doe about it", "capitalised"), ("reported by zoë", "person"),
                            ("cost was €1200", "money"), ("about 1,234,567 rows", "money"),
                            ("revenue fell to 400", "business_figure"), ("see data.debug.request", "dotted_name")):
            self.assertIn(check, self.soft(text), text)
            self.assertEqual(self.hard(text), [], text)
        out = build(with_(expected="I asked Jane Doe; revenue fell to 400."))
        self.assertEqual(out["changes"][0]["status"], "ready")
        self.assertTrue(any(w.get("soft") for w in out["changes"][0]["warnings"]))

    def test_2_names_unicode_and_single_after_triggers(self):
        for text in ("User Zoë", "reported by Łukasz Nowak", "profile of Søren", "customer José"):
            red = self.m.redact_text(text)
            self.assertIn("<name>", red, text)
        self.assertIn("person", self.soft("user jane"))
        self.assertEqual(self.soft("sorted by date"), [])
        self.assertEqual(self.soft("Expected: The rows"), [])

    def test_3_hosts_and_emails(self):
        self.assertNotIn("acme", self.m.redact_text("visit acme.com.br today"))
        self.assertEqual(self.m.redact_text("open data.json and notes.md"), "open data.json and notes.md")
        self.assertIn("url", self.hard("[link](https://evil.example/p)"))

    def test_4_keys(self):
        v = self.m.redact_value({"facets": {"color": {"red": 3}}, "topQueries": {"a": 1}, "Bad Key": 1,
                                 "lowerCamel": 1, "snake_key": 1, "big": {f"k{i}": i for i in range(12)}})
        self.assertEqual(sorted(v["facets"]), ["<key1>"])
        self.assertEqual(sorted(v["topQueries"]), ["<key1>"])
        self.assertIn("lowerCamel", v)
        self.assertIn("snake_key", v)
        self.assertNotIn("Bad Key", v)
        self.assertTrue(all(k.startswith("<key") for k in v["big"]))

    def test_5_enum_values_and_birth_dates(self):
        v = self.m.redact_value({"order": "asc", "sort": "Price DESC", "sort_direction": "desc", "dob": "1990-01-02",
                                 "birth_date": "1990-01-02", "start_date": "2026-10-01"})
        self.assertEqual(v["order"], "<order>")
        self.assertEqual(v["sort"], "<sort>")
        self.assertEqual(v["sort_direction"], "desc")
        self.assertEqual((v["dob"], v["birth_date"]), ("<dob>", "<birthdate>"))
        self.assertEqual(v["start_date"], "2026-10-01")

    def test_6_pair_separators_and_new_words(self):
        for text, leak in (("email == jane", "jane"), ("city != Paris", "Paris"), ("revenue >= 1200", "1200"),
                           ("segment in vip_list", "vip_list"), ("customer like jan", "jan"),
                           ("first_name: Ann", "Ann"), ("street=Main", "Main"), ("zip: 90210", "90210"),
                           ("client_ip: 10.0.0.1", "10.0"), ("aov = 42", "42"), ("price: 19", "19")):
            self.assertNotIn(leak, self.m.redact_text(text), text)

    def test_7_private_term_variants(self):
        terms = self.m.term_patterns(["Acme Outdoor"])
        for text in ("acme-outdoor", "ACME_OUTDOOR", "acme.outdoor", "AcmeOutdoor"):
            self.assertEqual(self.m.redact_text(text, terms), "<name>", text)
            self.assertIn("private_term", self.hard(text, ["Acme Outdoor"]))
        self.assertIn("private_term", checks(build(with_(tool="search_acme_outdoor"), "--private-terms",
                                                   self.write_terms("Acme Outdoor"))))

    def test_8_secrets(self):
        self.assertIn("secret", self.hard("aB3dE5fG7hI9kL1m"))
        for text in ("api key FAKE12345", "password hunter2FAKE", "sk_test_FAKEabc"):
            self.assertNotIn("FAKE", self.m.redact_text(text), text)
        self.assertEqual(self.m.redact_text("the token is invalid"), "the token is invalid")

    def test_9_cookies(self):
        for text in ("Set-Cookie: sid=FAKE; Path=/", "_ga=GA1.2.FAKE123", "x=a%3DFAKE"):
            red = self.m.redact_text(text)
            self.assertNotIn("FAKE", red, text)
            self.assertEqual(self.hard(red), [], red)
        self.assertIn("cookie", self.hard("Cookie: sid=FAKE"))
        self.assertIn("secret", self.hard("value a%3Db"))

    def test_12_only_the_repo_doc_url(self):
        ok_url = RULES["repo_doc_url"] + "#L10"
        self.assertEqual(self.hard(ok_url), [])
        for bad in (RULES["repo_doc_url"] + "?x=1", "https://github.com/bloomreach/loomi-connect-community/x",
                    RULES["repo_doc_url"] + "#token"):
            self.assertTrue(self.hard(bad), bad)

    def test_13_tool_must_be_published(self):
        self.assertIn("tool", checks(build(with_(tool="get_not_published"))))

    def test_15_empty_terms_block_unless_none_used(self):
        self.assertIn("private_terms", checks(build(GOOD, "--private-terms", self.write_terms(""))))
        none = self.write_terms(RULES["private_terms_none_line"])
        self.assertEqual(build(GOOD, "--private-terms", none)["changes"][0]["status"], "ready")

    def test_16_redacted_nested_values_dont_block(self):
        text = json.dumps(self.m.redact_value({"customer_ids": ["a", "b"], "filters": {"email": ["x"]}}))
        self.assertEqual(self.hard(text), [])


class Round4(unittest.TestCase):
    """Silent leaks left after round 3, with the coordinator's exact inputs."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def soft(self, text):
        return [h["check"] for h in self.m.lint_text("feedback", text, [])[1]]

    def test_1_client_and_model_are_never_sent(self):
        out = build(with_(client="Jane Doe laptop", model="acme-prod"))
        ch = out["changes"][0]
        sent = json.dumps(ch["payload"]) + out["payload_preview"]
        self.assertNotIn("Jane", sent)
        self.assertNotIn("acme-prod", sent)
        self.assertNotIn("client", ch["payload"])
        self.assertNotIn("model", ch["payload"])
        self.assertIn("client_model_ignored", [w["check"] for w in ch["warnings"]])

    def test_2_capitalised_name_at_sentence_start_and_in_quotes(self):
        self.assertIn("capitalised", self.soft("Jane Doe from merchandising saw it"))
        self.assertIn("quoted_name", self.soft("segment 'Big spenders - Jane Doe' failed"))
        out = build(with_(actual="Jane Doe from merchandising saw it",
                          response_excerpt=json.dumps({"error": "segment 'Big spenders - Jane Doe' failed"})))
        soft = [w["check"] for w in out["changes"][0]["warnings"] if w.get("soft")]
        self.assertIn("capitalised", soft)
        self.assertIn("quoted_name", soft)
        self.assertEqual(self.soft("The Loomi Connect team"), [])

    def test_3_domain_keys_and_account_tokens(self):
        self.assertNotIn("acme_us_en", self.m.redact_text("domain key acme_us_en"))
        self.assertIn("separated_token", self.soft("acme-fr-fr"))
        self.assertNotIn("separated_token", self.soft("get_discovery_category_performance_table"))
        self.assertNotIn("separated_token", self.soft("disabled_customization_ids"))

    def test_4_short_numeric_ids_after_context_words(self):
        for text in ("acct 6012", "Discovery account 6012", "site 7"):
            red = self.m.redact_text(text)
            self.assertFalse(any(c.isdigit() for c in red), red)
        self.assertEqual(self.m.redact_text("site search and account and project names"),
                         "site search and account and project names")

    def test_5_unusual_enum_values_warn(self):
        out = build(with_(arguments={"status": "acme_vip_list", "fl": "pid,acme_secret_attr"}))
        ch = out["changes"][0]
        self.assertEqual(ch["status"], "ready")
        warned = [w for w in ch["warnings"] if w["check"] == "argument_value"]
        self.assertEqual(len(warned), 2)
        clean = build(with_(arguments={"status": "active", "fl": "pid,brand"}))
        self.assertFalse([w for w in clean["changes"][0]["warnings"] if w["check"] == "argument_value"])


class VerifyWording(unittest.TestCase):
    def verify_json(self, response):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            ok(run("build", "--report", FX / "report_good.json", "--environment", "production", "--known-doc", DOC,
                   "--private-terms", FX / "private-terms.txt", "--out", plan, cwd=tmp))
            resp = Path(tmp) / "resp.json"
            resp.write_text(response if isinstance(response, str) else json.dumps(response), encoding="utf-8")
            return ok(run("verify", "--plan", plan, "--response", f"1={resp}", cwd=tmp))["results"][0]

    def test_negated_success_is_not_accepted(self):
        self.assertEqual(self.verify_json({"success": True, "message": "Feedback could not be recorded"})["state"],
                         "unknown")
        self.assertEqual(self.verify_json({"status": "received"})["state"], "unknown")
        self.assertEqual(self.verify_json("Feedback not received")["state"], "unknown")
        self.assertEqual(self.verify_json("Thank you, feedback received")["state"], "unknown")
        self.assertEqual(self.verify_json({"success": True})["state"], "accepted")
        self.assertEqual(self.verify_json({"data": {"id": "fb-2"}})["feedback_id"], "fb-2")

    def test_rate_note_uses_the_rule(self):
        res = self.verify_json({"success": False, "error": "HTTP 429"})
        self.assertIn("min_seconds_between_reports", res["note"])
        self.assertIn(str(RULES["min_seconds_between_reports"]), res["note"])


class Rules(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        keys = set(RULES) - {"about", "notes"}
        self.assertEqual(sorted(keys - set(RULES["notes"])), [])
        self.assertEqual(sorted(set(RULES["notes"]) - keys), [])
        self.assertTrue(RULES["about"])

    def test_rate_limit_keys_are_named_not_numbered_in_skill_md(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for key in ("min_seconds_between_reports", "max_reports_per_hour"):
            self.assertIn(key, text)
            self.assertIn(key, RULES)
        self.assertNotIn("10 seconds", text)
        self.assertNotIn("20 an hour", text)


if __name__ == "__main__":
    unittest.main()
