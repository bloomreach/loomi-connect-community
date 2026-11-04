"""Tests for engagement-sms-builder's sms_draft_plan.py: the SMS lint (encoding and segments, STOP, brand, HELP, links,
Jinja, placeholders), consent, sender and audience checks, quiet hours and state windows, the create and update plans
(the shape in docs/skill-authoring.md, with project_id in place of account and environment), the senders list and
verify. All fixtures are synthetic."""
import ast
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-sms-builder"
SCRIPT = SKILL / "scripts/sms_draft_plan.py"
FX = ROOT / "tests/fixtures/engagement/engagement-sms-builder"
RULES = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
GOOD = json.loads((FX / "draft_good.json").read_text(encoding="utf-8"))
CHANGE_KEYS = ("n", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
               "problems", "warnings")
SAT_1600_UTC = 1795276800  # 2026-11-21 16:00 UTC, a Saturday
SUN_1700_UTC = 1795366800  # 2026-11-22 17:00 UTC, a Sunday


def run(*args):
    """Run the script by its full path from an empty folder, as the assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def draft_with(**kw):
    d = json.loads(json.dumps(GOOD))
    d.update(kw)
    return d


def plan(draft=None, extra=(), audience=("--segmentations", FX / "segmentation.json"), ok=True, stdout=False):
    """The full plan from --out (or the printed summary with stdout=True, or the process with ok=False)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "draft.json"
        d.write_text(json.dumps(draft if draft is not None else GOOD), encoding="utf-8")
        out = ["--out", Path(tmp) / "plan.json"] if "--out" not in extra else []
        r = run("plan", "--draft", d, "--project-id", "proj-demo", "--project-name", "Demo project",
                "--consent", FX / "consent.json", "--campaigns", FX / "campaign_a.json",
                "--campaigns", FX / "campaign_b.json", *audience, *extra, *out)
        if not ok:
            return r
        assert r.returncode == 0, r.stdout + r.stderr
        if stdout:
            return r.stdout
        return json.loads((Path(tmp) / "plan.json").read_text(encoding="utf-8")) if out else json.loads(r.stdout)


def change(out):
    return out["changes"][0]


def problems(out):
    return [p["check"] for p in change(out)["problems"]]


def warnings(out):
    return [w["check"] for w in change(out)["warnings"]]


def msg(text):
    return draft_with(message=text)


class PlanShapeTest(unittest.TestCase):
    def test_good_draft_is_a_ready_create_with_the_shared_plan_shape(self):
        out = plan()
        for k in ("ok", "project_id", "project_name", "changes", "batches", "summary", "counts"):
            self.assertIn(k, out)
        c = change(out)
        for k in CHANGE_KEYS:
            self.assertIn(k, c)
        self.assertEqual(c["status"], "ready", c["problems"])
        self.assertEqual((c["kind"], c["tool"], c["live_impact"]), ("create", "create_sms_campaign", "none"))
        self.assertEqual(c["undo"], [])
        self.assertIn("undo_note", c)
        self.assertEqual(out["batches"], [[1]])
        self.assertEqual(out["counts"], {"ready": 1, "blocked": 0, "no_change": 0})

    def test_payload_matches_the_tool_schema(self):
        p = change(plan())["payload"]
        self.assertEqual(p["project_id"], "proj-demo")
        body = p["payload"]
        self.assertEqual(body["schedule"], {"type": "now"})
        self.assertEqual(body["split"], {"type": "off"})
        self.assertEqual(body["action"]["consent_category"], "sms_marketing")
        tr = body["action"]["variants"][0]
        self.assertEqual(tr["type"], "sms")
        self.assertEqual(list(tr["translations"]), [""])
        self.assertEqual(tr["translations"][""]["sender"], {"name": "Acme Outdoor", "sender": "AcmeOutdr"})
        self.assertEqual(body["customer_filter"]["formula"], "F0")
        self.assertEqual(body["customer_filter"]["filters"][0]["attribute"], {"type": "segmentation", "id": "seg-tiers"})

    def test_schedule_now_warns_what_it_means_and_silent_hours_always_warn(self):
        out = plan()
        self.assertIn("schedule", warnings(out))
        self.assertIn("silent_hours", warnings(out))
        self.assertIn("as soon as a person starts it", out["summary"]["schedule"])

    def test_translations_keep_the_default_language(self):
        out = plan(draft_with(translations={"es": "Acme Outdoor: 20% en botas. https://go.acme-outdoor.example/b "
                                                  "Responde STOP para salir, HELP ayuda"}))
        tr = change(out)["payload"]["payload"]["action"]["variants"][0]["translations"]
        self.assertEqual(sorted(tr), ["", "es"])
        self.assertEqual(sorted(out["summary"]["message_stats"]), ["", "es"])

    def test_customer_filter_audience_is_copied(self):
        out = plan(draft_with(audience={"type": "customer_filter", "customer_filter_id": "cf-boots"}),
                   audience=("--customer-filters", FX / "customer_filter.json"))
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])
        self.assertEqual(change(out)["payload"]["payload"]["customer_filter"]["formula"], "F0")

    def test_deterministic_and_out(self):
        a, b = plan(), plan()
        a.pop("plan_file"), b.pop("plan_file")
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            plan(extra=("--out", out))
            self.assertTrue(out.read_text(encoding="utf-8").endswith("\n"))

    def test_out_to_a_missing_folder_fails_cleanly(self):
        r = plan(extra=("--out", Path(tempfile.gettempdir()) / "no-such-folder-sms" / "plan.json"), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])


class EncodingTest(unittest.TestCase):
    def stats(self, text):
        return plan(msg(text))["summary"]["message_stats"][""]

    def test_gsm7_single_and_multi_segment_thresholds(self):
        base = "Acme Outdoor: Reply STOP to opt out, HELP for help. "
        one = base + "x" * (RULES["gsm7_single_chars"] - len(base))
        two = one + "x"
        self.assertEqual((self.stats(one)["encoding"], self.stats(one)["segments"]), ("GSM-7", 1))
        self.assertEqual(self.stats(two)["segments"], 2)
        three = base + "x" * (RULES["gsm7_part_chars"] * 2 + 1 - len(base))
        self.assertEqual(self.stats(three)["segments"], 3)
        self.assertIn("length", warnings(plan(msg(three))))

    def test_extension_characters_count_twice(self):
        base = "Acme Outdoor: Reply STOP to opt out, HELP for help. "
        text = base + "x" * (RULES["gsm7_single_chars"] - len(base) - 1) + "€"
        s = self.stats(text)
        self.assertEqual((s["encoding"], s["chars"], s["segments"]), ("GSM-7", RULES["gsm7_single_chars"] + 1, 2))

    def test_ucs2_thresholds_and_emoji(self):
        base = "Acme Outdoor ✓ STOP HELP "
        one = base + "x" * (RULES["ucs2_single_chars"] - len(base))
        self.assertEqual((self.stats(one)["encoding"], self.stats(one)["segments"]), ("UCS-2", 1))
        self.assertEqual(self.stats(one + "x")["segments"], 2)
        emoji = "Acme Outdoor: 🎉 Reply STOP to opt out, HELP for help"
        s = self.stats(emoji)
        self.assertEqual(s["encoding"], "UCS-2")
        self.assertEqual(s["chars"], len(emoji) + 1)  # an emoji is two UTF-16 units
        self.assertIn("encoding", warnings(plan(msg(emoji))))

    def test_curly_quotes_get_their_own_warning(self):
        out = plan(msg("Acme Outdoor: it’s 20% off. Reply STOP to opt out, HELP for help"))
        w = [x for x in change(out)["warnings"] if x["check"] == "encoding"]
        self.assertTrue(w and "straight" in w[0]["message"])

    def test_jinja_counts_as_estimate(self):
        s = self.stats("Acme Outdoor: {{ customer['first_name'] | default('x', true) }} STOP HELP")
        self.assertEqual(s["chars"], len("Acme Outdoor:  STOP HELP") + RULES["jinja_estimate_chars"])

    def test_over_max_segments_is_blocked(self):
        text = "Acme Outdoor: STOP HELP " + "x" * (RULES["gsm7_part_chars"] * RULES["max_segments"] + 1)
        self.assertIn("length", problems(plan(msg(text))))


class ComplianceTest(unittest.TestCase):
    def test_missing_stop_blocks_unless_transactional(self):
        text = "Acme Outdoor: 20% off boots. HELP for help"
        self.assertIn("opt_out", problems(plan(msg(text))))
        out = plan(draft_with(message=text, transactional=True))
        self.assertNotIn("opt_out", problems(out))
        self.assertIn("opt_out", warnings(out))

    def test_help_warns_or_blocks_for_regulated(self):
        text = "Acme Outdoor: 20% off boots. Reply STOP to opt out"
        self.assertIn("help", warnings(plan(msg(text))))
        self.assertIn("help", problems(plan(draft_with(message=text, regulated_industry=True))))

    def test_brand_window(self):
        late = "Hi there, this is a long opening before the name, Acme Outdoor. STOP HELP"
        self.assertIn("brand", warnings(plan(msg(late))))
        self.assertIn("brand", problems(plan(draft_with(message=late, regions=["US-TX"]))))
        self.assertIn("brand", problems(plan(draft_with(brand=""))))

    def test_canada_needs_a_link(self):
        text = "Acme Outdoor: 20% off boots. Reply STOP to opt out, HELP for help"
        self.assertIn("casl_contact", problems(plan(draft_with(message=text, regions=["CA"]))))
        self.assertNotIn("casl_contact", problems(plan(draft_with(regions=["CA"]))))

    def test_assumed_regions_are_said(self):
        out = plan(draft_with(regions=[]))
        self.assertIn("regions", warnings(out))
        self.assertTrue(out["summary"]["regions_assumed"])
        self.assertIn("texas_sb140", warnings(out))
        self.assertIn("three_per_day", warnings(out))

    def test_restricted_terms_warn(self):
        out = plan(msg("Acme Outdoor: new craft beer gift sets. Reply STOP to opt out, HELP for help"))
        self.assertIn("restricted_content", warnings(out))


class LinkTest(unittest.TestCase):
    def check(self, link, **kw):
        return plan(draft_with(message=f"Acme Outdoor: boots {link} Reply STOP to opt out, HELP for help", **kw))

    def test_supplied_host_and_subdomain_pass(self):
        self.assertEqual(change(self.check("https://go.acme-outdoor.example/b"))["status"], "ready")
        out = self.check("https://m.go.acme-outdoor.example/b")
        self.assertNotIn("unknown_link_host", problems(out))
        self.assertEqual(out["summary"]["link_hosts"], ["m.go.acme-outdoor.example"])

    def test_http_www_and_bare_domains_are_blocked(self):
        self.assertIn("links", problems(self.check("http://go.acme-outdoor.example/b")))
        self.assertIn("links", problems(self.check("www.go.acme-outdoor.example/b")))
        self.assertIn("links", problems(self.check("go.acme-outdoor.example/boots")))
        self.assertIn("links", problems(self.check("ftp://go.acme-outdoor.example/boots")))

    def test_unknown_and_placeholder_hosts(self):
        self.assertIn("unknown_link_host", problems(self.check("https://shop.other-brand.example/b")))
        self.assertIn("links", problems(self.check("https://example.com/b")))

    def test_public_shortener_warns_even_when_supplied(self):
        out = self.check("https://bit.ly/abc", user_supplied_hosts=["bit.ly"])
        self.assertIn("public_shortener", warnings(out))
        self.assertNotIn("unknown_link_host", problems(out))

    def test_customer_data_in_a_link_is_blocked_even_on_a_supplied_host(self):
        out = self.check("https://go.acme-outdoor.example/b?id={{ customer.customer_id | default('', true) }}")
        self.assertIn("link_personal_data", problems(out))

    def test_backslash_and_user_info_hosts_are_blocked(self):
        for link in ("https://evil.example\\@go.acme-outdoor.example/x", "https://evil.example@go.acme-outdoor.example/x",
                     "https://go.acme-outdoor.example\\evil.example/x"):
            with self.subTest(link=link):
                out = self.check(link)
                self.assertIn("link_host_form", problems(out))
                self.assertEqual(change(out)["status"], "blocked")
        self.assertNotIn("link_host_form", problems(self.check("https://go.acme-outdoor.example/x?a=b@c")))

    def test_jinja_in_the_host_is_blocked(self):
        for link in ('https://go.acme-outdoor.example{{ ".evil.example" }}/x', "https://{{ host }}/x",
                     "{{ scheme }}://go.acme-outdoor.example/x"):
            with self.subTest(link=link):
                self.assertIn("link_host_form", problems(self.check(link)))

    def test_full_links_are_in_the_summary(self):
        out = self.check("https://go.acme-outdoor.example/b?x=1")
        self.assertEqual(out["summary"]["links"], ["https://go.acme-outdoor.example/b?x=1"])

    def test_other_jinja_in_a_link_warns(self):
        out = self.check("https://go.acme-outdoor.example/b?c={{ vouchers['VIP'].assign_available() }}")
        self.assertIn("link_jinja", warnings(out))


class JinjaAndPlaceholderTest(unittest.TestCase):
    def test_placeholders(self):
        for bad in ("[URL]", "<link>", "{{FNAME}}", "*|FNAME|*", "TODO", "{{ }}", "%%CODE%%"):
            with self.subTest(bad=bad):
                self.assertIn("placeholder", problems(plan(msg(f"Acme Outdoor: boots {bad} STOP HELP"))))

    def test_placeholder_in_the_name(self):
        self.assertIn("placeholder", problems(plan(draft_with(name="TODO name"))))

    def test_jinja_rules(self):
        base = "Acme Outdoor: {} Reply STOP to opt out, HELP for help"
        self.assertIn("jinja_delimiters", problems(plan(msg(base.format("{{ customer.first_name")))))
        self.assertIn("jinja_blocks", problems(plan(msg(base.format("{% if x %}hi")))))
        self.assertIn("jinja_rules", problems(plan(msg(base.format("{{ now | strftime('%d') }}")))))
        self.assertIn("jinja_rules", problems(plan(msg(base.format("{{ event.total }}")))))
        self.assertIn("personalization_fallback", problems(plan(msg(base.format("{{ customer.first_name }}")))))
        self.assertIn("jinja_default", warnings(plan(msg(base.format("{{ customer.first_name | default('x') }}")))))
        self.assertIn("jinja_escape", warnings(plan(msg(base.format(
            "{{ customer.first_name | default('x', true) | e }}")))))


class SettingsTest(unittest.TestCase):
    def test_consent(self):
        self.assertIn("consent", problems(plan(draft_with(consent_category=None))))
        self.assertIn("consent", problems(plan(draft_with(consent_category="nope"))))
        self.assertIn("consent", problems(plan(draft_with(consent_category=None, general_consent=True))))
        self.assertIn("consent", warnings(plan(draft_with(consent_category="existing_customers"))))
        self.assertIn("consent", warnings(plan(draft_with(consent_category="newsletter"))))  # STOP replies not a source

    def test_sender(self):
        self.assertIn("sender", problems(plan(draft_with(sender={"name": "Acme", "sender": "NewSender"}))))
        user = plan(draft_with(sender={"name": "Acme", "sender": "NewSender", "source": "user"}))
        self.assertNotIn("sender", problems(user))
        self.assertIn("sender", warnings(user))
        self.assertIn("sender", problems(plan(draft_with(sender={"name": "Acme", "sender": "TooLongSender1",
                                                                  "source": "user"}))))
        self.assertIn("sender", problems(plan(draft_with(sender={"name": "Acme", "sender": "12",
                                                                  "source": "user"}))))
        phone = plan(draft_with(sender={"name": "Acme", "sender": "+15550100", "source": "user"}))
        self.assertNotIn("sender", problems(phone))

    def test_audience(self):
        self.assertIn("audience", problems(plan(draft_with(audience={"type": "segment", "segmentation_id": "seg-tiers",
                                                                      "segment": "Nope"}))))
        self.assertIn("audience", problems(plan(draft_with(audience={"type": "everyone"}))))
        out = plan(draft_with(audience={"type": "everyone", "confirmed": True}))
        self.assertNotIn("customer_filter", change(out)["payload"]["payload"])

    def test_event_schedule_and_mms_are_refused(self):
        self.assertIn("schedule", problems(plan(draft_with(schedule={"type": "event", "event": {}}))))
        self.assertIn("type", problems(plan(draft_with(type="mms"))))

    def test_context_error_in_a_saved_result_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "consent.json"
            bad.write_text(json.dumps({"success": False, "error": "Access denied to project https://x.test/?k=FAKE"}),
                           encoding="utf-8")
            d = Path(tmp) / "draft.json"
            d.write_text(json.dumps(GOOD), encoding="utf-8")
            r = run("plan", "--draft", d, "--project-id", "p", "--project-name", "P", "--consent", bad,
                    "--out", Path(tmp) / "plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project, account or access", r.stdout)
        self.assertNotIn("FAKE", r.stdout)


class ScheduleTest(unittest.TestCase):
    def sched(self, ts, offsets, regions, today=None):
        extra = ("--today", today) if today else ()
        return plan(draft_with(schedule={"type": "datetime", "datetime": ts}, recipient_utc_offsets=offsets,
                               regions=regions), extra=extra)

    def test_inside_every_window_is_ready_with_local_times(self):
        out = self.sched(SAT_1600_UTC, ["-05:00", "-08:00"], ["US-NY"])  # 11:00 Eastern, 08:00 Pacific
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])
        self.assertEqual([t["local"] for t in out["summary"]["local_send_times"]],
                         ["2026-11-21 08:00", "2026-11-21 11:00"])
        self.assertEqual(change(out)["payload"]["payload"]["schedule"], {"type": "datetime", "datetime": SAT_1600_UTC})

    def test_quiet_hours_block(self):
        self.assertIn("quiet_hours", problems(self.sched(SAT_1600_UTC, ["-10:00"], ["US"])))  # 06:00 Hawaii

    def test_named_state_blocks_implied_state_warns(self):
        self.assertIn("state_window", problems(self.sched(SAT_1600_UTC, ["-08:00"], ["US-TX"])))  # 08:00 < 9
        out = self.sched(SAT_1600_UTC, ["-08:00"], ["US"])
        self.assertNotIn("state_window", problems(out))
        self.assertIn("state_window", warnings(out))

    def test_sunday_rules(self):
        self.assertIn("state_window", problems(self.sched(SUN_1700_UTC, ["-05:00"], ["US-FL"])))  # no Sundays
        self.assertNotIn("state_window", problems(self.sched(SUN_1700_UTC, ["-05:00"], ["US-TX"])))  # 12:00 is fine

    def test_offsets_required_and_validated(self):
        self.assertIn("schedule", problems(self.sched(SAT_1600_UTC, [], ["US"])))
        self.assertIn("schedule", problems(self.sched(SAT_1600_UTC, ["EST"], ["US"])))

    def test_milliseconds_and_float_strings_are_converted(self):
        out = self.sched(SAT_1600_UTC * 1000, ["-05:00"], ["US-NY"])
        self.assertEqual(change(out)["status"], "ready", change(out)["problems"])
        self.assertEqual(change(out)["payload"]["payload"]["schedule"]["datetime"], SAT_1600_UTC)
        self.assertTrue(any("milliseconds" in w["message"] for w in change(out)["warnings"]))
        out = self.sched(f"{SAT_1600_UTC}.0", ["-05:00"], ["US-NY"])
        self.assertEqual(change(out)["payload"]["payload"]["schedule"]["datetime"], SAT_1600_UTC)

    def test_unusable_datetimes_block_without_a_traceback(self):
        for bad in ("soon", None, "nan", "1e400", -5, 10 ** 30):
            with self.subTest(bad=bad):
                out = self.sched(bad, ["-05:00"], ["US-NY"])
                self.assertIn("schedule", problems(out))

    def test_past_and_today(self):
        self.assertIn("schedule", problems(self.sched(SAT_1600_UTC, ["-05:00"], ["US-NY"], today="2026-11-25")))
        out = self.sched(SAT_1600_UTC, ["-05:00"], ["US-NY"], today="2026-11-21")
        self.assertNotIn("schedule", problems(out))
        self.assertTrue(any("today" in w["message"] for w in change(out)["warnings"]))


class UpdateTest(unittest.TestCase):
    def existing(self, tmp, **changes):
        rec = json.loads((FX / "existing_draft.json").read_text(encoding="utf-8"))
        rec["result"]["data"].update(changes)
        p = Path(tmp) / "existing.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        return p

    def upd(self, draft, created_id="sms-new-1", stdout=False, **changes):
        with tempfile.TemporaryDirectory() as tmp:
            extra = ("--existing", self.existing(tmp, **changes))
            if created_id:
                extra += ("--created-id", created_id)
            return plan(draft, extra=extra, stdout=stdout)

    def draft(self, **kw):
        return draft_with(campaign_id="sms-new-1", origin="created_this_session", **kw)

    def test_unchanged_is_no_change(self):
        out = self.upd(self.draft())
        self.assertEqual(change(out)["status"], "no_change", change(out)["problems"])
        self.assertEqual(out["batches"], [])

    def test_message_change_is_an_update_built_from_the_fetched_campaign(self):
        new = GOOD["message"].replace("Sunday", "Monday")
        out = self.upd(self.draft(message=new))
        c = change(out)
        self.assertEqual((c["status"], c["kind"], c["tool"]), ("ready", "update", "update_sms_campaign"))
        self.assertEqual(sorted(c["before"]), ["messages"])
        self.assertEqual(c["after"]["messages"][""], new)
        body = c["payload"]["payload"]
        self.assertEqual(c["payload"]["campaign_id"], "sms-new-1")
        self.assertEqual(body["action"]["variants"][0]["translations"][""]["message"], new)
        # untouched keys and provider stubs survive the PUT
        self.assertEqual(body["action"]["transfer_user_identity"], "first_click")
        self.assertIn("sms", body["action"]["variants"][0]["translations"][""]["sender"])
        self.assertEqual(c["undo"][0]["tool"], "update_sms_campaign")
        self.assertNotIn("Monday", json.dumps(c["undo"]))

    def test_stdout_has_no_payload_or_editor_names_and_payload_is_cleaned(self):
        new = self.draft(message=GOOD["message"].replace("Sunday", "Monday"))
        text = self.upd(new, stdout=True)
        self.assertNotIn('"payload"', text)
        self.assertNotIn("display_name", text)
        self.assertNotIn("Example Editor", text)
        c = change(self.upd(new))
        for part in (c["payload"], c["undo"]):
            dumped = json.dumps(part)
            self.assertNotIn("display_name", dumped)
            self.assertNotIn('"edited"', dumped)
            self.assertNotIn('"active"', dumped)
        self.assertEqual(c["payload"]["payload"]["schedule"], {"type": "now"})

    def test_out_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "draft.json"
            d.write_text(json.dumps(GOOD), encoding="utf-8")
            r = run("plan", "--draft", d, "--project-id", "p", "--project-name", "P", "--consent", FX / "consent.json")
        self.assertNotEqual(r.returncode, 0)

    def test_created_id_must_match_for_created_this_session(self):
        new = self.draft(name="x DRAFT")
        self.assertNotIn("target", problems(self.upd(new)))
        self.assertIn("target", problems(self.upd(new, created_id=None)))
        self.assertIn("target", problems(self.upd(new, created_id="sms-other")))
        named = draft_with(campaign_id="sms-new-1", origin="user_named", user_confirmed=True, name="x DRAFT")
        self.assertNotIn("target", problems(self.upd(named, created_id=None)))

    def test_only_drafts_are_edited(self):
        for status in ("active", "inactive", "finished"):
            with self.subTest(status=status):
                self.assertIn("target", problems(self.upd(self.draft(name="x DRAFT"), status=status)))
        self.assertIn("target", problems(self.upd(self.draft(name="x DRAFT"), locked=True)))
        self.assertIn("target", problems(self.upd(self.draft(name="x DRAFT"), split={"type": "manual"})))

    def test_origin_rules(self):
        self.assertIn("target", problems(self.upd(draft_with(campaign_id="sms-new-1", name="x DRAFT"))))
        named = draft_with(campaign_id="sms-new-1", origin="user_named", name="x DRAFT")
        self.assertIn("target", problems(self.upd(named)))
        named["user_confirmed"] = True
        self.assertNotIn("target", problems(self.upd(named)))
        self.assertIn("target", problems(self.upd(self.draft(name="x DRAFT") | {"campaign_id": "other"})))


class SendersTest(unittest.TestCase):
    def test_default_skips_placeholder_names(self):
        r = run("senders", "--campaigns", FX / "campaign_a.json", "--campaigns", FX / "campaign_b.json")
        out = json.loads(r.stdout)
        self.assertEqual([s["sender"] for s in out["senders"]], ["Demo", "AcmeOutdr"])
        self.assertTrue(out["senders"][0]["looks_like_placeholder"])
        self.assertEqual(out["default"]["sender"], "AcmeOutdr")


class VerifyTest(unittest.TestCase):
    def verify(self, readback, draft=None):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps(plan(draft)), encoding="utf-8")
            return run("verify", "--plan", p, "--readback", f"1={readback}")

    def test_in_place(self):
        out = json.loads(self.verify(FX / "readback_ok.json").stdout)
        self.assertEqual(out["results"][0]["state"], "in_place")
        self.assertNotIn("alert", out["results"][0])

    def test_changed_message_and_not_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = json.loads((FX / "readback_ok.json").read_text(encoding="utf-8"))
            d = rec["result"]["data"]
            d["status"] = "active"
            d["action"]["variants"][0]["translations"][""]["message"] = "different"
            p = Path(tmp) / "rb.json"
            p.write_text(json.dumps(rec), encoding="utf-8")
            res = json.loads(self.verify(p).stdout)["results"][0]
        self.assertEqual(res["state"], "not_in_place")
        self.assertIn("message['']", [m["field"] for m in res["mismatches"]])
        self.assertIn("alert", res)

    def test_not_found_and_context_error(self):
        res = json.loads(self.verify(FX / "readback_not_found.json").stdout)["results"][0]
        self.assertEqual(res["state"], "not_in_place")
        r = self.verify(FX / "readback_project_error.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project, account or access", r.stdout)

    def test_readback_argument_splits_on_first_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "a=b.json"
            odd.write_text((FX / "readback_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
            out = json.loads(self.verify(odd).stdout)
        self.assertEqual(out["results"][0]["state"], "in_place")

    def test_blocked_plan_cannot_be_verified(self):
        r = self.verify(FX / "readback_ok.json", draft=draft_with(consent_category=None))
        self.assertEqual(r.returncode, 1)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        self.assertIn("about", RULES)
        self.assertEqual(set(RULES) - {"about", "notes"}, set(RULES["notes"]))

    def test_shared_values_match_campaign_qa(self):
        qa = json.loads((ROOT / "plugins/loomi-engagement/skills/campaign-qa/references/rules.json")
                        .read_text(encoding="utf-8"))
        for k in ("jinja_estimate_chars", "sms_brand_window_chars", "placeholder_hosts", "public_shorteners",
                  "restricted_terms"):
            self.assertEqual(RULES[k], qa[k], k)

    def test_banned_jinja_matches_the_email_builder(self):
        email = json.loads((ROOT / "plugins/loomi-engagement/skills/engagement-email-builder/references/rules.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(RULES["banned_jinja"], email["banned_jinja"])

    def test_fixtures_end_with_a_newline(self):
        for f in FX.iterdir():
            self.assertTrue(f.read_text(encoding="utf-8").endswith("\n"), f.name)


def str_value(node):
    """A string literal, or literals joined with +, from campaign-qa's source."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return str_value(node.left) + str_value(node.right)
    raise ValueError(ast.dump(node))


class CampaignQaParityTest(unittest.TestCase):
    """Values this skill copies from campaign-qa's message_checks.py and message-checks.md must stay the same."""

    @classmethod
    def setUpClass(cls):
        qa = ROOT / "plugins/loomi-engagement/skills/campaign-qa"
        cls.qa_src = (qa / "scripts/message_checks.py").read_text(encoding="utf-8")
        cls.qa_tree = ast.parse(cls.qa_src)
        cls.qa_md = (qa / "references/message-checks.md").read_text(encoding="utf-8")
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("sms_draft_plan_under_test", SCRIPT)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def qa_set(self, name):
        for node in self.qa_tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
                call = node.value
                self.assertEqual(call.func.id, "set")
                return set(str_value(call.args[0]))
        self.fail(f"{name} not found in message_checks.py")

    def qa_function(self, name):
        return next(n for n in self.qa_tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_gsm7_alphabets(self):
        self.assertEqual(self.mod.GSM7, self.qa_set("GSM7"))
        self.assertEqual(self.mod.GSM7_EXT, self.qa_set("GSM7_EXT"))

    def test_segment_sizes(self):
        src = ast.get_source_segment(self.qa_src, self.qa_function("sms_segments"))
        sizes = [(int(a), int(b)) for a, b in re.findall(r"n <= (\d+) else math\.ceil\(n / (\d+)\)", src)]
        self.assertEqual(sizes, [(RULES["gsm7_single_chars"], RULES["gsm7_part_chars"]),
                                 (RULES["ucs2_single_chars"], RULES["ucs2_part_chars"])])

    def test_opt_out_pattern(self):
        patterns = [str_value(c.args[0]) for c in ast.walk(self.qa_function("check_sms"))
                    if isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "search"
                    and c.args and isinstance(c.args[0], ast.Constant) and "stop" in str(c.args[0].value)]
        self.assertEqual(patterns, [RULES["opt_out_pattern"]])

    def table_row(self, label):
        line = next(l.strip() for l in self.qa_md.splitlines() if l.strip().startswith(f"| {label}"))
        return line.split("|")[2]

    def names(self, pred):
        return {w["name"] for w in RULES["state_windows"].values() if pred(w)}

    def test_state_windows_match_the_table(self):
        self.assertEqual(self.names(lambda w: w["weekday"][0] > RULES["federal_window"]["start_hour"]),
                         {s.strip() for s in self.table_row("Starts before 9 a.m.").split(",")})
        late = {s.strip() for s in self.table_row("Ends after 8 p.m.").split(",")}
        self.assertEqual(self.names(lambda w: w["weekday"][1] == 20), late)
        sunday = self.table_row("Sends on Sunday")
        no_sunday = {s.strip() for s in sunday.split("(no Sunday contact)")[0].split(",")}
        self.assertEqual(self.names(lambda w: w.get("sunday") == "none"), no_sunday)
        self.assertIn("Texas (noon", sunday)
        self.assertEqual(RULES["state_windows"]["US-TX"]["sunday"][0], 12)
        self.assertIn("Rhode Island (9 a.m.–6 p.m. weekdays, 9 a.m.–5 p.m. Saturday)", self.qa_md)
        self.assertEqual((RULES["state_windows"]["US-RI"]["weekday"], RULES["state_windows"]["US-RI"]["saturday"]),
                         ([9, 18], [9, 17]))
        self.assertIn("Federal baseline: 8 a.m.–9 p.m.", self.qa_md)
        self.assertEqual((RULES["federal_window"]["start_hour"], RULES["federal_window"]["end_hour"]), (8, 21))

    def test_three_per_day_states(self):
        m = re.search(r"\*\*Three-per-24-hours limit\.\*\* ([A-Z][a-z]+), ([A-Z][a-z]+) and ([A-Z][a-z]+) limit",
                      self.qa_md)
        self.assertIsNotNone(m)
        self.assertEqual({RULES["state_windows"][c]["name"] for c in RULES["three_per_day_states"]}, set(m.groups()))


if __name__ == "__main__":
    unittest.main()
