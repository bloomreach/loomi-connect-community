"""Tests for engagement-email-builder's email_draft_plan.py: the lint that blocks a draft, the plan file (the shape in
docs/skill-authoring.md, with project_id in place of account and environment), the senders list, and verify on the
read-back. All fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-email-builder"
SCRIPT = SKILL / "scripts/email_draft_plan.py"
FX = ROOT / "tests/fixtures/engagement/engagement-email-builder"
GOOD_HTML = (FX / "email_good.html").read_text(encoding="utf-8")
GOOD_DRAFT = json.loads((FX / "draft_good.json").read_text(encoding="utf-8"))
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")


def run(*args):
    """Run the script by its full path from an empty folder, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def plan(html=GOOD_HTML, draft=None, extra=(), audience_files=("--segmentations", FX / "segmentation.json")):
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / "email.html"
        h.write_text(html, encoding="utf-8")
        d = Path(tmp) / "draft.json"
        d.write_text(json.dumps(draft if draft is not None else GOOD_DRAFT), encoding="utf-8")
        r = run("plan", "--draft", d, "--html", h, "--project-id", "proj-demo", "--project-name", "Demo project",
                "--consent", FX / "consent.json", "--campaigns", FX / "campaign_a.json",
                "--campaigns", FX / "campaign_b.json", *audience_files, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def change(out):
    return out["changes"][0]


def problems(out):
    return [p["check"] for p in change(out)["problems"]]


def warnings(out):
    return [w["check"] for w in change(out)["warnings"]]


def draft_with(**kw):
    d = json.loads(json.dumps(GOOD_DRAFT))
    d.update(kw)
    return d


class PlanShapeTest(unittest.TestCase):
    def test_good_draft_is_ready_with_the_shared_plan_shape(self):
        out = plan()
        for k in ("ok", "project_id", "project_name", "changes", "batches", "summary", "counts"):
            self.assertIn(k, out)
        c = change(out)
        for k in CHANGE_KEYS:
            self.assertIn(k, c)
        self.assertEqual(c["status"], "ready", c["problems"])
        self.assertEqual((c["n"], c["kind"], c["tool"], c["live_impact"]), (1, "create", "create_email_campaign", "none"))
        self.assertIsNone(c["before"])
        self.assertEqual(c["undo"], [])
        self.assertIn("undo_note", c)
        self.assertEqual(out["batches"], [[1]])
        self.assertEqual(out["counts"], {"ready": 1, "blocked": 0, "no_change": 0})

    def test_payload_is_a_raw_draft_with_segment_audience_and_consent(self):
        c = change(plan())
        self.assertEqual(c["payload"]["project_id"], "proj-demo")
        p = c["payload"]["payload"]
        self.assertEqual(p["schedule"], {"type": "now"})
        self.assertEqual(p["consent_category"], "newsletter")
        self.assertNotIn("general_consent", p)
        self.assertNotIn("design", p)  # create takes split only
        self.assertEqual(p["split"]["type"], "off")
        design = p["split"]["variants"][0]["design"]
        self.assertEqual(design["type"], "raw")
        self.assertEqual(design["data"]["jinja_html"], GOOD_HTML)
        self.assertEqual(design["data"]["sender_email"], "news@acme-outdoor.example")
        self.assertNotIn("provider", design["data"])  # project default integration
        atom = p["customer_filter"]["filters"][0]
        self.assertEqual(atom["attribute"], {"type": "segmentation", "id": "seg0000000000000000000001"})
        self.assertEqual(atom["constraint"]["operands"], [{"type": "constant", "value": "Lapsed VIP"}])
        self.assertEqual(p["customer_filter"]["formula"], "F0")
        self.assertEqual(c["after"]["status"], "draft")

    def test_two_segments_are_ored(self):
        p = change(plan(draft=draft_with(audience={"type": "segment", "segmentation_id": "seg0000000000000000000001",
                                                   "segments": ["VIP", "Lapsed VIP"]})))["payload"]["payload"]
        self.assertEqual(p["customer_filter"]["formula"], "F0|F1")

    def test_customer_filter_is_copied_unchanged(self):
        out = plan(draft=draft_with(audience={"type": "customer_filter", "customer_filter_id": "cf00000000000000000000001"}),
                   audience_files=("--customer-filters", FX / "customer_filter.json"))
        saved = json.loads((FX / "customer_filter.json").read_text(encoding="utf-8"))["data"]
        cf = change(out)["payload"]["payload"]["customer_filter"]
        self.assertEqual(cf, {"filters": saved["filters"], "formula": saved["formula"]})

    def test_output_is_deterministic_and_written_with_out(self):
        self.assertEqual(plan(), plan())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            res = plan(extra=("--out", out))
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), res)

    def test_out_to_a_missing_folder_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Path(tmp) / "e.html"
            h.write_text(GOOD_HTML, encoding="utf-8")
            r = run("plan", "--draft", FX / "draft_good.json", "--html", h, "--project-id", "p", "--project-name", "n",
                    "--consent", FX / "consent.json", "--campaigns", FX / "campaign_a.json",
                    "--segmentations", FX / "segmentation.json", "--out", Path(tmp) / "no" / "such" / "plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])


class LintBlockingTest(unittest.TestCase):
    def assertBlocked(self, out, check):
        self.assertEqual(change(out)["status"], "blocked")
        self.assertIn(check, problems(out))
        self.assertEqual(out["batches"], [])

    def test_missing_unsubscribe(self):
        self.assertBlocked(plan(GOOD_HTML.replace("{{ consent.page }}", "https://www.acme-outdoor.example/prefs")),
                           "unsubscribe")

    def test_missing_postal_address(self):
        self.assertBlocked(plan(GOOD_HTML.replace("{{ project_variables.company_address }}", "")), "postal_address")

    def test_literal_postal_address_counts_when_declared(self):
        html = GOOD_HTML.replace("{{ project_variables.company_address }}", "1 Trail Road, Springfield, ST 00000")
        out = plan(html, draft=draft_with(postal_address="1 Trail Road, Springfield, ST 00000"))
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])

    def test_unbalanced_jinja(self):
        self.assertBlocked(plan(GOOD_HTML.replace("{{ item['title'] | default('', true) | e }}</p>",
                                                  "{{ item['title'] | default('', true) | e </p>")), "jinja_delimiters")
        self.assertBlocked(plan(GOOD_HTML.replace("{% endif %}\n  <tr><td align=\"center\" style=\"padding:16px 24px 32px;\">",
                                                  "\n  <tr><td align=\"center\" style=\"padding:16px 24px 32px;\">")),
                           "jinja_blocks")

    def test_css_closing_braces_are_not_stray_jinja(self):
        self.assertNotIn("jinja_delimiters", problems(plan()))  # the @media block ends with "}" then "}"

    def test_script_and_event_handlers(self):
        self.assertBlocked(plan(GOOD_HTML.replace("</body>", "<script>alert(1)</script></body>")), "script")
        self.assertBlocked(plan(GOOD_HTML.replace("<h1 style", "<h1 onclick=\"x()\" style")), "script")

    def test_unknown_image_host_and_tracking_pixel(self):
        self.assertBlocked(plan(GOOD_HTML.replace("https://brxcdn.com/acme/logo.png", "https://cdn.other.example/logo.png")),
                           "unknown_host")
        pixel = '<img src="https://track.ads.example/p.gif" width="1" height="1" alt="">'
        self.assertBlocked(plan(GOOD_HTML.replace("</body>", pixel + "</body>")), "tracking_pixel")

    def test_user_supplied_host_is_allowed(self):
        html = GOOD_HTML.replace("https://brxcdn.com/acme/logo.png", "https://img.acme-outdoor.example/logo.png")
        out = plan(html, draft=draft_with(user_supplied_hosts=["acme-outdoor.example"]))
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])

    def test_alt_text(self):
        self.assertBlocked(plan(GOOD_HTML.replace(' alt="Acme Outdoor"', "")), "alt_text")

    def test_subject_length(self):
        self.assertIn("subject", warnings(plan(draft=draft_with(subject="A" * 70))))
        self.assertBlocked(plan(draft=draft_with(subject="A" * 120)), "subject")
        self.assertBlocked(plan(draft=draft_with(subject="")), "subject")

    def test_placeholder_text(self):
        self.assertBlocked(plan(GOOD_HTML.replace("first access", "lorem ipsum")), "placeholder")
        self.assertBlocked(plan(GOOD_HTML.replace("first access", "TODO copy")), "placeholder")
        self.assertBlocked(plan(GOOD_HTML.replace("first access", "{{ }}")), "placeholder")
        self.assertBlocked(plan(GOOD_HTML.replace("Shop the sale", "%%CTA_TEXT%%")), "placeholder")

    def test_starter_template_is_blocked_until_filled(self):
        starter = (SKILL / "assets/starter-email.html").read_text(encoding="utf-8")
        out = plan(starter)
        self.assertEqual(change(out)["status"], "blocked")
        self.assertIn("placeholder", problems(out))

    def test_jinja_rules(self):
        self.assertBlocked(plan(GOOD_HTML.replace("recommendations('5f0000000000000000000001'", "recommendations(engine")),
                           "jinja_rules")
        self.assertBlocked(plan(GOOD_HTML.replace("Black Friday.</p>", "Black Friday {{ event.total }}.</p>")), "jinja_rules")
        for fn in ("max(1, 2)", "min(1, 2)"):
            self.assertBlocked(plan(GOOD_HTML.replace("Black Friday.</p>", "Black Friday {{ " + fn + " }}.</p>")),
                               "jinja_rules")
        self.assertBlocked(plan(draft=draft_with(subject="Hi {{ customer.first_name }}")), "personalization_fallback")
        self.assertIn("jinja_default", warnings(plan(draft=draft_with(subject="Hi {{ customer.first_name | default('x') }}"))))

    def test_links(self):
        self.assertBlocked(plan(GOOD_HTML.replace('href="https://www.acme-outdoor.example/black-friday"', 'href="#"')), "links")
        self.assertBlocked(plan(GOOD_HTML.replace("https://www.acme-outdoor.example/black-friday", "www.acme-outdoor.example")),
                           "links")


class LintBypassTest(unittest.TestCase):
    """Ways to load outside content that the lint must still see."""

    def assertBlocked(self, out, check):
        self.assertEqual(change(out)["status"], "blocked")
        self.assertIn(check, problems(out))

    def test_links_and_images_whose_host_is_disguised_are_blocked(self):
        host = GOOD_DRAFT["user_supplied_hosts"][0]
        for tag in (f'<a href="https://evil.example\\@{host}/x">x</a>',
                    f'<a href="https://evil.example@{host}/x">x</a>',
                    f'<a href="https://{host}{{{{ \'.evil.example\' }}}}/x">x</a>',
                    f'<a href="{{{{ scheme }}}}://{host}/x">x</a>',
                    f'<img src="https://evil.example\\@{host}/p.png" alt="x" width="1" height="1">',
                    f'<img src="https://evil.example\\@{host}/p.png" alt="x" width="300">'):
            with self.subTest(tag=tag):
                self.assertBlocked(plan(GOOD_HTML.replace("</body>", tag + "</body>")), "url_host_form")

    def test_data_driven_links_still_pass_the_host_form_check(self):
        out = plan(GOOD_HTML.replace("</body>", '<a href="{{ item.url }}">x</a></body>'))
        self.assertNotIn("url_host_form", problems(out))

    def test_jinja_image_src_with_a_literal_host_is_host_checked(self):  # 1a
        img = '<img src="{{ \'https://cdn.evil.example/x.png\' if true else \'\' }}" alt="x" width="100">'
        self.assertBlocked(plan(GOOD_HTML.replace("</body>", img + "</body>")), "unknown_host")

    def test_customer_data_in_an_image_url_is_blocked(self):  # 1a
        for src in ("https://brxcdn.com/p.png?e={{ customer['email'] | default('', true) }}",
                    "{{ 'https://brxcdn.com/p.png?e=' ~ customer.email }}"):
            img = f'<img src="{src}" alt="x" width="100">'
            self.assertBlocked(plan(GOOD_HTML.replace("</body>", img + "</body>")), "image_personal_data")
        pixel = '<img src="https://img.acme-outdoor.example/p.gif?id={{ customer_ids.registered }}" width="1" height="1" alt="">'
        self.assertBlocked(plan(GOOD_HTML.replace("</body>", pixel + "</body>")), "tracking_pixel")

    def test_srcset_poster_and_source_are_checked(self):  # 1b
        for tag in ('<img src="https://brxcdn.com/a.png" srcset="https://brxcdn.com/a2.png 2x, https://cdn.evil.example/b.png 3x" alt="a">',
                    '<video poster="https://cdn.evil.example/poster.png"></video>',
                    '<video><source src="https://cdn.evil.example/clip.mp4"></video>'):
            self.assertBlocked(plan(GOOD_HTML.replace("</body>", tag + "</body>")), "unknown_host")

    def test_iframe_embed_object_are_blocked(self):  # 1b
        for tag in ('<iframe src="https://brxcdn.com/x.html"></iframe>', '<embed src="https://brxcdn.com/x.swf">',
                    '<object data="https://brxcdn.com/x.svg"></object>'):
            self.assertBlocked(plan(GOOD_HTML.replace("</body>", tag + "</body>")), "embed")

    def test_outlook_conditional_comments_cannot_hide_images(self):  # 1c
        mso = ('<!--[if mso]><v:rect><v:fill src="https://cdn.evil.example/bg.png"/></v:rect>'
               '<img src="https://track.ads.example/o.gif" width="1" height="1" alt=""><![endif]-->')
        out = plan(GOOD_HTML.replace("</body>", mso + "</body>"))
        self.assertIn("unknown_host", problems(out))
        self.assertIn("tracking_pixel", problems(out))

    def test_customer_data_in_a_link_needs_a_supplied_host(self):  # 1d
        own = '<a href="https://www.acme-outdoor.example/vip?e={{ customer.email | default(\'\', true) | e }}">VIP</a>'
        self.assertNotIn("link_personal_data", problems(plan(GOOD_HTML.replace("</body>", own + "</body>"))))
        other = own.replace("www.acme-outdoor.example", "partner.other.example")
        self.assertBlocked(plan(GOOD_HTML.replace("</body>", other + "</body>")), "link_personal_data")
        whole = '<a href="{{ customer.referral_url | default(\'\', true) }}">Refer</a>'
        self.assertBlocked(plan(GOOD_HTML.replace("</body>", whole + "</body>")), "link_personal_data")

    def test_third_party_link_host_warns_and_hosts_are_summarised(self):  # 1d, 1e
        link = '<a href="https://partner.other.example/deal">Partner deal</a>'
        out = plan(GOOD_HTML.replace("</body>", link + "</body>"))
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])
        self.assertIn("third_party_link", warnings(out))
        self.assertEqual(out["summary"]["link_hosts"], ["partner.other.example", "www.acme-outdoor.example"])
        self.assertEqual(out["summary"]["image_hosts"], ["(from data)", "brxcdn.com"])

    def test_messages_never_suggest_import_media_file(self):  # 2
        out = plan(GOOD_HTML.replace("https://brxcdn.com/acme/logo.png", "https://cdn.other.example/logo.png")
                   .replace('alt="Acme Outdoor" width="160"', 'alt="Acme Outdoor" width="160" srcset="data:image/png;base64,AAAA"'))
        text = json.dumps(change(out))
        self.assertNotIn("import_media_file", text)
        self.assertIn("Ask the user to upload it to the Engagement media library", text)
        self.assertNotIn("import_media_file", SCRIPT.read_text(encoding="utf-8"))


class ContextChecksTest(unittest.TestCase):
    def test_unknown_sender_is_blocked(self):
        out = plan(draft=draft_with(sender={"name": "Someone", "email": "new@other.example", "source": "user"}))
        self.assertIn("sender", problems(out))

    def test_other_existing_sender_is_fine(self):
        out = plan(draft=draft_with(sender={"name": "Acme Deals", "email": "deals@acme-outdoor.example", "source": "user"}))
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])

    def test_missing_or_wrong_segment(self):
        self.assertIn("audience", problems(plan(draft=draft_with(audience={"type": "segment",
                      "segmentation_id": "seg0000000000000000000001", "segment": "Nope"}))))
        self.assertIn("audience", problems(plan(audience_files=())))
        self.assertIn("audience", problems(plan(draft=draft_with(audience={"type": "everyone"}))))

    def test_consent(self):
        self.assertIn("consent", problems(plan(draft=draft_with(consent_category=None))))
        self.assertIn("consent", problems(plan(draft=draft_with(consent_category="nope"))))
        self.assertIn("consent", problems(plan(draft=draft_with(general_consent=True))))  # both set, and not allowed
        self.assertIn("consent", warnings(plan(draft=draft_with(consent_category="transactional_li"))))

    def test_context_error_in_a_saved_result_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "seg.json"
            bad.write_text((FX / "readback_project_error.json").read_text(encoding="utf-8"), encoding="utf-8")
            h = Path(tmp) / "e.html"
            h.write_text(GOOD_HTML, encoding="utf-8")
            r = run("plan", "--draft", FX / "draft_good.json", "--html", h, "--project-id", "p", "--project-name", "n",
                    "--consent", FX / "consent.json", "--campaigns", FX / "campaign_a.json", "--segmentations", bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("project", json.loads(r.stdout)["error"])


class SendersTest(unittest.TestCase):
    def test_newest_sender_first_counted_once_per_campaign(self):
        r = run("senders", "--campaigns", FX / "campaign_b.json", "--campaigns", FX / "campaign_a.json")
        out = json.loads(r.stdout)
        self.assertEqual(out["default"]["sender_email"], "news@acme-outdoor.example")
        self.assertEqual([s["campaigns"] for s in out["senders"]], [1, 1])


class VerifyTest(unittest.TestCase):
    def verify(self, readback):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps(plan()), encoding="utf-8")
            return run("verify", "--plan", p, "--readback", f"1={FX / readback}")

    def test_in_place(self):
        r = self.verify("readback_ok.json")
        res = json.loads(r.stdout)["results"][0]
        self.assertEqual(res["state"], "in_place", res.get("mismatches"))
        self.assertTrue(res["html_matches"])
        self.assertEqual(res["campaign_id"], "new000000000000000000001")
        self.assertNotIn("alert", res)

    def test_not_in_place_and_not_a_draft(self):
        res = json.loads(self.verify("readback_changed.json").stdout)["results"][0]
        self.assertEqual(res["state"], "not_in_place")
        self.assertEqual(sorted(m["field"] for m in res["mismatches"]), ["status", "subject"])
        self.assertIn("alert", res)

    def test_not_found_is_not_in_place(self):
        res = json.loads(self.verify("readback_not_found.json").stdout)["results"][0]
        self.assertEqual(res["state"], "not_in_place")
        self.assertIn("search_email_campaigns", res["note"])

    def test_context_error_stops(self):
        for f in ("readback_project_error.json", "readback_rate_limited.json"):
            r = self.verify(f)
            self.assertEqual(r.returncode, 1, f)
            self.assertFalse(json.loads(r.stdout)["ok"])

    def test_stripped_design_stops(self):
        r = self.verify("readback_no_design.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("include_design", json.loads(r.stdout)["error"])

    def test_readback_argument_splits_on_first_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "a=b.json"
            odd.write_text((FX / "readback_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps(plan()), encoding="utf-8")
            r = run("verify", "--plan", p, "--readback", f"1={odd}")
        self.assertEqual(json.loads(r.stdout)["results"][0]["state"], "in_place")

    def test_blocked_plan_cannot_be_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps(plan(draft=draft_with(subject=""))), encoding="utf-8")
            r = run("verify", "--plan", p, "--readback", f"1={FX / 'readback_ok.json'}")
        self.assertEqual(r.returncode, 1)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertIn("about", rules)
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
