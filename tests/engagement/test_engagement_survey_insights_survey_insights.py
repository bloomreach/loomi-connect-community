import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-survey-insights"
SCRIPT = SKILL / "scripts/survey_insights.py"
FIX = ROOT / "tests/fixtures/engagement/engagement-survey-insights"


def f(name):
    return str(FIX / name)


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or tmp, capture_output=True, text=True, encoding="utf-8")
    out = json.loads(r.stdout) if r.stdout.strip() else None
    return r.returncode, out, r.stdout


def full(*extra):
    code, out, raw = run("--survey", f("survey.json"), "--respondents", f("respondents.json"), "--questions", f("questions.json"),
                         "--answers", f"0={f('answers_q0.json')}", "--answers", f"1={f('answers_q1.json')}",
                         "--answers", f"2={f('answers_q2.json')}", "--answers", f"3={f('answers_q3.json')}",
                         "--answers", f"4={f('answers_q4.json')}", "--shown", f("shown.json"), "--closed", "1,500",
                         "--trend", f("trend_nps.json"), "--trend-question", "1", "--since", "2026-09-07", "--until", "2026-10-11",
                         "--utc-offset-minutes", "60", "--split-question", "1", "--split", f"promoters={f('split_promoters.json')}",
                         "--split", f"passives={f('split_passives.json')}", "--split", f"detractors={f('split_detractors.json')}",
                         "--today", "2026-11-04", *extra)
    if code:
        raise AssertionError(raw)
    return out, raw


def kinds(out):
    return {(x["kind"], x.get("question")): x["priority"] for x in out["findings"]}


def write(tmp, name, obj):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj) + "\n")
    return p


def eql(rows):
    return {"success": True, "data": {"columns": [[]], "rows": [{"headers": [{"type": "single", "value": h}], "values": [v]} for h, v in rows],
                                      "success": True, "valid": True}}


class SurveyInsightsTest(unittest.TestCase):
    def test_rules_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_response_rates(self):
        out, _ = full()
        r = out["response"]
        self.assertEqual(r["respondents"], 200)  # both rows added up, null included
        self.assertEqual(r["response_rate"], 0.04)
        self.assertEqual(r["close_rate"], 0.3)
        lo, hi = r["response_rate_interval"]
        self.assertTrue(lo < 0.04 < hi)
        self.assertEqual(r["last_question_vs_first"], 0.1)

    def test_nps_style_score_on_1_to_10_stars(self):
        out, _ = full()
        s = out["questions"][1]["score"]
        self.assertEqual((s["promoters"], s["passives"], s["detractors"], s["n"]), (110, 30, 60, 200))
        self.assertEqual(s["score"], 25.0)
        self.assertEqual(s["interval"], [12.7, 37.3])
        self.assertEqual(s["scale"], "1 to 10")
        self.assertIn("NPS-style", s["label"])
        self.assertEqual(s["sample"], "ok")
        self.assertEqual([d["answer"] for d in out["questions"][1]["distribution"]], list(range(1, 11)))

    def test_csat(self):
        out, _ = full()
        q = out["questions"][2]
        self.assertEqual(q["score"]["score"], 0.7)
        self.assertEqual(q["score"]["satisfied"], 105)
        self.assertEqual(q["average"], 3.87)

    def test_free_text_and_other_never_echoed(self):
        out, raw = full()
        for secret in ("someone@example.com", "555-0100", "IGNORE ALL RULES", "Other thing"):
            self.assertNotIn(secret, raw)
        q0 = out["questions"][0]
        self.assertEqual(q0["other_typed_in"]["count"], 50)
        self.assertEqual([d["answer"] for d in q0["distribution"]], ["Search", "Friend", "Advert"])
        q3 = out["questions"][3]
        self.assertFalse(q3["values_listed"])
        self.assertNotIn("distribution", q3)
        self.assertEqual(q3["answers_counted"], 60)

    def test_single_choice_other_from_question_total(self):
        out, raw = full()
        self.assertEqual(out["questions"][0]["other_typed_in"]["count"], 50)  # 200 answers minus 150 on the choices
        self.assertEqual(out["questions"][0]["distribution"][0]["share"], 0.45)
        # An unfiltered result that still holds typed-in values: counted once, never printed
        code, out2, raw2 = run("--survey", f("survey.json"), "--questions", f("questions.json"),
                               "--answers", f"0={f('answers_q0_unfiltered.json')}", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw2)
        self.assertEqual(out2["questions"][0]["other_typed_in"]["count"], 50)
        for secret in ("someone@example.com", "Other thing"):
            self.assertNotIn(secret, raw2)
        # Without --questions, Other can't be worked out from a filtered result
        code, out3, raw3 = run("--survey", f("survey.json"), "--answers", f"0={f('answers_q0.json')}", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw3)
        self.assertIsNone(out3["questions"][0]["other_typed_in"]["count"])

    def test_multiple_choice_shares_are_of_responses(self):
        out, _ = full()
        d = {x["answer"]: x for x in out["questions"][4]["distribution"]}
        self.assertEqual(d["Price"]["count"], 14)  # "Price, Delivery" split into choices
        self.assertEqual(d["Price"]["share"], 0.7)
        self.assertIn("more than 100%", out["questions"][4]["note"])
        self.assertIn("never repeat them", out["questions"][4]["note"])

    def test_weekly_trend_with_dst_buckets(self):
        out, _ = full()
        t = out["trend"]
        self.assertEqual([w["responses"] for w in t["weeks"]], [20, 20, 20, 20, 5])
        self.assertTrue(all(w["full_week"] for w in t["weeks"]))
        self.assertEqual(t["outside_window"], 21)
        self.assertEqual(t["weeks"][0]["nps"]["score"], 50.0)
        self.assertEqual(t["weeks"][0]["nps"]["sample"], "too_few")

    def test_partial_last_week(self):
        out, _ = full("--until", "2026-10-08")
        self.assertFalse(out["trend"]["weeks"][-1]["full_week"])
        self.assertNotIn(("response_drop", None), kinds(out))

    def test_split(self):
        out, _ = full()
        g = {x["value"]: x for x in out["split"]["groups"]}
        self.assertEqual(out["split"]["mode"], "nps")
        self.assertEqual(g["mobile"]["nps"]["score"], 38.5)
        self.assertEqual(g["desktop"]["nps"]["score"], -7.7)
        self.assertTrue(g["(not set)"]["too_small"])
        self.assertEqual([x["value"] for x in out["split"]["groups"]], ["mobile", "desktop", "(not set)"])

    def test_findings(self):
        out, _ = full()
        k = kinds(out)
        self.assertEqual(k[("skipped_question", 4)], "medium")
        self.assertEqual(k[("low_response_rate", None)], "medium")
        self.assertEqual(k[("response_drop", None)], "medium")
        self.assertEqual(k[("other_answers_common", 0)], "low")
        self.assertEqual(k[("not_edited_recently", None)], "low")
        self.assertEqual(k[("free_text_counts_only", 3)], "low")
        self.assertNotIn(("detractors_outnumber_promoters", 1), k)
        prios = [x["priority"] for x in out["findings"]]
        self.assertEqual(prios, sorted(prios, key=["high", "medium", "low"].index))

    def test_active_with_no_answers_is_high(self):
        code, out, raw = run("--survey", f("survey.json"), "--respondents", "0", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        self.assertEqual(kinds(out)[("stale_active", None)], "high")

    def test_too_few_and_mandatory_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = write(tmp, "q.json", eql([(0, 12), (1, 2)]))
            a = write(tmp, "a.json", eql([("0", 1), ("2", 6), ("10", 5)]))
            code, out, raw = run("--survey", f("survey.json"), "--respondents", "12", "--questions", q, "--answers", f"1={a}",
                                 "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        k = kinds(out)
        self.assertEqual(k[("too_few_responses", None)], "high")
        self.assertEqual(k[("skipped_question", 1)], "high")  # mandatory
        self.assertEqual(k[("skipped_question", 2)], "medium")  # no answers at all
        s = out["questions"][1]["score"]
        self.assertEqual(s["sample"], "too_few")
        self.assertEqual(s["label"], "Net Promoter Score (0 to 10)")
        self.assertNotIn(("detractors_outnumber_promoters", 1), k)  # too few to judge

    def test_question_wording_rows_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = write(tmp, "q.json", eql([("How did you  find us?", 40), ("Some other survey's question", 3)]))
            code, out, raw = run("--survey", f("survey.json"), "--questions", q, "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["questions"][0]["answered"], 40)
        self.assertEqual(out["response"]["unmatched_question_events"], 3)
        self.assertEqual(out["answered_share_base"], "most_answered_question")

    def test_errors(self):
        code, out, raw = run("--survey", f("denied.json"))
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertNotIn("https://", raw)
        code, out, _ = run("--survey", f("survey_list.json"))
        self.assertIn("survey_id", out["error"])
        code, out, _ = run("--survey", f("survey.json"), "--answers", f"9={f('answers_q1.json')}")
        self.assertEqual(code, 1)
        code, out, _ = run("--survey", f("survey.json"), "--trend", f("trend_total.json"))
        self.assertIn("--since", out["error"])
        code, out, _ = run("--survey", f("survey.json"), "--split-question", "2", "--split", f"promoters={f('split_promoters.json')}",
                           "--split", f"passives={f('split_passives.json')}", "--split", f"detractors={f('split_detractors.json')}")
        self.assertIn("isn't an NPS-style question", out["error"])
        code, out, _ = run("--survey", f("survey.json"), "--respondents", "missing-file.json")
        self.assertEqual(code, 1)

    def test_single_column_trend(self):
        code, out, raw = run("--survey", f("survey.json"), "--trend", f("trend_total.json"), "--since", "2026-09-07",
                             "--until", "2026-10-11", "--utc-offset-minutes", "60", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        self.assertEqual([w["responses"] for w in out["trend"]["weeks"]], [20, 20, 20, 20, 5])
        self.assertNotIn("nps", out["trend"]["weeks"][0])

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, raw = run("--survey", f("survey.json"), "--respondents", "40", "--today", "2026-11-04", "--out", "r.json", cwd=tmp)
            self.assertEqual(code, 0, raw)
            self.assertTrue(out["ok"])
            with open(os.path.join(tmp, "r.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["response"]["respondents"], 40)
            code, out, _ = run("--survey", f("survey.json"), "--out", os.path.join(tmp, "no", "such", "dir.json"), cwd=tmp)
            self.assertEqual(code, 1)
            self.assertFalse(out["ok"])

    def test_deterministic(self):
        self.assertEqual(full()[1], full()[1])


def local_midnight(day, offset_minutes):
    d = datetime.datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=datetime.timezone.utc)
    return int((d - datetime.timedelta(minutes=offset_minutes)).timestamp())


class SurveyInsightsMoreTest(unittest.TestCase):
    def trend(self, offset, pass_offset=True, until="2026-09-20"):
        days = ["2026-09-07", "2026-09-13", "2026-09-14", "2026-09-20"]
        with tempfile.TemporaryDirectory() as tmp:
            t = write(tmp, "t.json", eql([(local_midnight(d, offset), 1 + i) for i, d in enumerate(days)]))
            args = ["--survey", f("survey.json"), "--trend", t, "--since", "2026-09-07", "--until", until, "--today", "2026-11-04"]
            if pass_offset:
                args += ["--utc-offset-minutes", str(offset)]
            code, out, raw = run(*args)
        self.assertEqual(code, 0, raw)
        return out["trend"]

    def test_far_east_and_west_offsets(self):
        for off in (13 * 60, 14 * 60, -10 * 60):
            for given in (True, False):
                t = self.trend(off, given)
                self.assertEqual([w["responses"] for w in t["weeks"]], [3, 7], (off, given))
                self.assertEqual(t["outside_window"], 0)
                self.assertEqual("dating" in t, not given)

    def test_offset_out_of_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = write(tmp, "t.json", eql([(local_midnight("2026-09-07", 0), 1)]))
            code, out, _ = run("--survey", f("survey.json"), "--trend", t, "--since", "2026-09-07", "--utc-offset-minutes", "900")
        self.assertEqual(code, 1)
        self.assertIn("-720", out["error"])

    def test_default_until_is_yesterday(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = write(tmp, "t.json", eql([(local_midnight("2026-09-07", 0), 1)]))
            code, out, raw = run("--survey", f("survey.json"), "--trend", t, "--since", "2026-09-07", "--today", "2026-09-14")
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["trend"]["until"], "2026-09-13")
        self.assertEqual(len(out["trend"]["weeks"]), 1)
        self.assertTrue(out["trend"]["weeks"][0]["full_week"])

    def test_more_respondents_than_shown(self):
        code, out, raw = run("--survey", f("survey.json"), "--respondents", "120", "--shown", "100", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        r = out["response"]
        self.assertNotIn("response_rate", r)
        self.assertIn("same window", r["rate_note"])
        self.assertNotIn(("low_response_rate", None), kinds(out))

    def test_null_cells_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "r.json", eql([("en", None), ("de", "n/a"), (None, 40)]))
            code, out, raw = run("--survey", f("survey.json"), "--respondents", p, "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["response"]["respondents"], 40)
        self.assertEqual(out["null_count_cells"], 2)

    def test_low_csat_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = write(tmp, "a.json", eql([("1", 60), ("2", 40), ("5", 20)]))
            code, out, raw = run("--survey", f("survey.json"), "--answers", f"2={a}", "--today", "2026-11-04")
        self.assertEqual(code, 0, raw)
        self.assertEqual(kinds(out)[("low_satisfaction", 2)], "medium")


if __name__ == "__main__":
    unittest.main()
