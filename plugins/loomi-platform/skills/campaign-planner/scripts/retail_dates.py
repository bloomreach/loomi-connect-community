#!/usr/bin/env python3
"""Work out retail and cultural moment dates for any year and market.

Standard library only. No network access.

Usage:
  python3 retail_dates.py --year 2027
  python3 retail_dates.py --market UK,DE --from 2026-10-08 --to 2026-12-31
  python3 retail_dates.py --market AU --year 2027          # unknown market: Global only, plus a warning
  python3 retail_dates.py --market US --from 2026-10-08 --weeks 8 --json

Markets with their own rules: US, UK, EU, and the EU countries DE, FR, NL, ES, IT.
"EU" returns pan-EU moments plus every EU-country moment, labelled by country.
"GLOBAL" moments are always included. Any other market code is accepted: the
script returns the Global moments and says that the market has no section yet.
The default market is US,UK,EU.

Window filtering (--from/--to or --from/--weeks) keeps a moment when either the
moment itself or its promotion start (the moment minus its lead time) falls in
the window, so you also see moments you need to start promoting now.

Status of each date:
  computed   worked out here from a fixed rule (Gregorian, Easter algorithm).
  verified   from the lookup table below, checked against published sources.
  verify     from the lookup table, but provisional (moon sighting, regional
             calendars, or an announced-but-changeable retailer event).
  look up    not computable offline and not in the table for that year.

Lunar and retailer-announced dates are in LOOKUP. The owner should extend it
every year; references/retail-calendar.md is the human-readable source.
"""

import argparse
import json
import sys
from datetime import date, timedelta

EU_COUNTRIES = {"DE", "FR", "NL", "ES", "IT"}
KNOWN_MARKETS = {"GLOBAL", "US", "UK", "EU"} | EU_COUNTRIES


# ---------- date helpers ----------

def easter(year):
    """Gregorian Easter Sunday (Anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year, month, weekday, n):
    """n-th weekday (Mon=0) of a month; n=-1 for the last."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta((weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(1)
    return d - timedelta((d.weekday() - weekday) % 7)


def weekday_on_or_before(d, weekday):
    return d - timedelta((d.weekday() - weekday) % 7)


def substitute(d):
    """UK-style substitute day: Sat/Sun move to the next Monday."""
    if d.weekday() == 5:
        return d + timedelta(2)
    if d.weekday() == 6:
        return d + timedelta(1)
    return d


def uk_christmas_pair(year):
    xmas, boxing = date(year, 12, 25), date(year, 12, 26)
    if xmas.weekday() == 5:      # Sat: Mon 27, Tue 28
        return date(year, 12, 27), date(year, 12, 28)
    if xmas.weekday() == 6:      # Sun: Tue 27 (Christmas), Mon 26 is Boxing Day
        return date(year, 12, 27), boxing
    if boxing.weekday() == 5:    # Fri Christmas, Sat Boxing -> Mon 28
        return xmas, date(year, 12, 28)
    return xmas, boxing


def thanksgiving(y):
    return nth_weekday(y, 11, 3, 4)


def fr_mothers_day(y):
    d = nth_weekday(y, 5, 6, -1)
    if d == easter(y) + timedelta(49):   # clashes with Pentecost
        d = nth_weekday(y, 6, 6, 1)
    return d


def fr_winter_sales(y):
    d = nth_weekday(y, 1, 2, 2)
    return d if d.day <= 12 else nth_weekday(y, 1, 2, 1)


def fr_summer_sales(y):
    d = nth_weekday(y, 6, 2, -1)
    return d if d.day <= 28 else d - timedelta(7)


def nl_kings_day(y):
    d = date(y, 4, 27)
    return d - timedelta(1) if d.weekday() == 6 else d


def first_advent(y):
    return weekday_on_or_before(date(y, 12, 24), 6) - timedelta(weeks=3)


# Lunar and announced dates. "verified" = checked against published sources;
# "verify" = provisional. Extend every year (owner should update yearly).
LOOKUP = {
    "lunar_new_year": {2026: ("2026-02-17", "verified"), 2027: ("2027-02-06", "verified")},
    "ramadan_start": {2026: ("2026-02-18", "verify"), 2027: ("2027-02-08", "verify")},
    "eid_al_fitr": {2026: ("2026-03-20", "verify"), 2027: ("2027-03-09", "verify")},
    "eid_al_adha": {2026: ("2026-05-27", "verify"), 2027: ("2027-05-16", "verify")},
    "diwali": {2026: ("2026-11-08", "verified"), 2027: ("2027-10-29", "verify")},
    "holi": {2026: ("2026-03-03", "verify"), 2027: ("2027-03-22", "verify")},
    "hanukkah": {2026: ("2026-12-04", "verified"), 2027: ("2027-12-24", "verified")},
    "prime_day_summer": {2025: ("2025-07-08", "verified"), 2026: ("2026-06-23", "verify")},
    "prime_day_october": {2025: ("2025-10-07", "verified"), 2026: ("2026-10-06", "verified")},
}


def lookup(key):
    def f(y):
        hit = LOOKUP.get(key, {}).get(y)
        if not hit:
            return None, "look up"
        return date.fromisoformat(hit[0]), hit[1]
    return f


def fixed(month, day):
    return lambda y: date(y, month, day)


# ---------- moments ----------
# (id, name, markets, rule, function(year) -> date | (date, status), lead_days, categories)
M = [
    # Global
    ("valentines", "Valentine's Day", {"GLOBAL"}, "14 February", fixed(2, 14), 21, "jewellery, gifts, lingerie, fragrance, dining"),
    ("lunar_new_year", "Lunar New Year", {"GLOBAL"}, "new moon between 21 Jan and 20 Feb (lunisolar)", lookup("lunar_new_year"), 28, "gifts, red/gold apparel, food, travel; shipping cut-offs"),
    ("intl_womens_day", "International Women's Day", {"GLOBAL"}, "8 March", fixed(3, 8), 14, "womenswear, beauty, purpose-led"),
    ("ramadan_start", "Ramadan begins", {"GLOBAL"}, "1 Ramadan (moon sighting); about 11 days earlier each year", lookup("ramadan_start"), 21, "modest fashion, home, food, gifting for Eid"),
    ("eid_al_fitr", "Eid al-Fitr", {"GLOBAL"}, "1 Shawwal (moon sighting)", lookup("eid_al_fitr"), 28, "new outfits, gifts, jewellery, home"),
    ("eid_al_adha", "Eid al-Adha", {"GLOBAL"}, "10 Dhu al-Hijjah (moon sighting)", lookup("eid_al_adha"), 21, "apparel, gifts, travel"),
    ("holi", "Holi", {"GLOBAL"}, "Phalguna full moon (Hindu calendar)", lookup("holi"), 14, "white apparel, colour, beauty"),
    ("easter", "Easter Sunday", {"GLOBAL"}, "first Sunday after the paschal full moon (computed)", easter, 21, "spring fashion, kids, confectionery, home"),
    ("halloween", "Halloween", {"GLOBAL"}, "31 October", fixed(10, 31), 28, "costumes, kids, home decor, beauty"),
    ("diwali", "Diwali", {"GLOBAL"}, "Kartika new moon (Hindu calendar; regional calendars can differ by a day)", lookup("diwali"), 28, "jewellery, ethnic wear, home, gifts, electronics"),
    ("singles_day", "Singles' Day (11.11)", {"GLOBAL"}, "11 November", fixed(11, 11), 10, "everything, deep discounts; strongest in APAC, growing in EU"),
    ("black_friday", "Black Friday", {"GLOBAL"}, "day after US Thanksgiving (4th Thursday of November)", lambda y: thanksgiving(y) + timedelta(1), 28, "everything; electronics, fashion, beauty, home"),
    ("cyber_monday", "Cyber Monday", {"GLOBAL"}, "Monday after Black Friday", lambda y: thanksgiving(y) + timedelta(4), 7, "online-first offers, electronics, fashion"),
    ("hanukkah", "Hanukkah begins (evening)", {"GLOBAL"}, "25 Kislev (Hebrew calendar), 8 nights", lookup("hanukkah"), 21, "gifts, home, kids"),
    ("double_twelve", "Double 12 (12.12)", {"GLOBAL"}, "12 December", fixed(12, 12), 7, "last-chance holiday deals; APAC"),
    ("christmas", "Christmas Day", {"GLOBAL"}, "25 December", fixed(12, 25), 56, "gifting across all categories; party wear"),
    ("new_years_eve", "New Year's Eve", {"GLOBAL"}, "31 December", fixed(12, 31), 14, "party wear, beauty, drinks"),
    ("new_year", "New Year / January reset", {"GLOBAL"}, "1 January", fixed(1, 1), 7, "activewear, wellness, organisation, sale clearance"),

    # US
    ("us_mlk", "Martin Luther King Jr. Day", {"US"}, "3rd Monday of January", lambda y: nth_weekday(y, 1, 0, 3), 7, "long-weekend sales, winter clearance"),
    ("us_super_bowl", "Super Bowl Sunday", {"US"}, "2nd Sunday of February since 2022 (confirm each season)", lambda y: (nth_weekday(y, 2, 6, 2), "verify"), 14, "TVs, snacks, team apparel, home"),
    ("us_presidents", "Presidents' Day", {"US"}, "3rd Monday of February", lambda y: nth_weekday(y, 2, 0, 3), 7, "mattresses, furniture, appliances, winter clearance"),
    ("us_mothers", "Mother's Day (US, DE, NL, IT)", {"US", "DE", "NL", "IT"}, "2nd Sunday of May", lambda y: nth_weekday(y, 5, 6, 2), 21, "jewellery, flowers, beauty, apparel, gifts"),
    ("us_memorial", "Memorial Day", {"US"}, "last Monday of May", lambda y: nth_weekday(y, 5, 0, -1), 10, "summer kick-off, outdoor, furniture, apparel"),
    ("us_fathers", "Father's Day (US, UK, FR, NL)", {"US", "UK", "FR", "NL"}, "3rd Sunday of June", lambda y: nth_weekday(y, 6, 6, 3), 21, "menswear, grooming, tech, tools, outdoor"),
    ("prime_day_summer", "Amazon Prime Day (summer)", {"US", "UK", "EU"}, "announced by Amazon, usually June or July", lookup("prime_day_summer"), 7, "counter-programme: electronics, home, fashion"),
    ("us_july4", "Independence Day", {"US"}, "4 July", fixed(7, 4), 10, "summer apparel, outdoor, BBQ, red/white/blue"),
    ("us_back_to_school", "Back to school (US peak start)", {"US"}, "mid-July to Labor Day; peaks 2 weeks before local term", fixed(7, 15), 21, "kids apparel, shoes, bags, stationery, laptops"),
    ("us_labor", "Labor Day", {"US"}, "1st Monday of September", lambda y: nth_weekday(y, 9, 0, 1), 10, "end-of-summer clearance, mattresses, appliances"),
    ("prime_day_october", "Prime Big Deal Days (October)", {"US", "UK", "EU"}, "announced by Amazon, usually early October", lookup("prime_day_october"), 7, "early holiday deals, electronics, home"),
    ("us_indigenous", "Columbus / Indigenous Peoples' Day", {"US"}, "2nd Monday of October", lambda y: nth_weekday(y, 10, 0, 2), 7, "fall sales, outerwear"),
    ("us_veterans", "Veterans Day", {"US"}, "11 November", fixed(11, 11), 7, "early holiday sales, mattresses, outdoor"),
    ("us_thanksgiving", "Thanksgiving", {"US"}, "4th Thursday of November", thanksgiving, 21, "home, hosting, food; launches Black Friday week"),
    ("us_small_business_sat", "Small Business Saturday", {"US"}, "Saturday after Thanksgiving", lambda y: thanksgiving(y) + timedelta(2), 7, "independent and local brands"),
    ("us_giving_tuesday", "Giving Tuesday", {"US"}, "Tuesday after Thanksgiving", lambda y: thanksgiving(y) + timedelta(5), 7, "charity tie-ins, purpose-led"),
    ("us_green_monday", "Green Monday", {"US"}, "2nd Monday of December", lambda y: nth_weekday(y, 12, 0, 2), 7, "last reliable shipping for gifts"),
    ("us_super_saturday", "Super Saturday", {"US"}, "last Saturday before Christmas", lambda y: weekday_on_or_before(date(y, 12, 24), 5), 7, "last-minute gifts, BOPIS, gift cards"),

    # UK
    ("uk_new_year_bh", "New Year's Day bank holiday", {"UK"}, "1 January, or next weekday", lambda y: substitute(date(y, 1, 1)), 7, "January sales"),
    ("uk_pancake", "Pancake Day (Shrove Tuesday)", {"UK"}, "47 days before Easter", lambda y: easter(y) - timedelta(47), 10, "food, kitchen"),
    ("uk_mothering_sunday", "Mothering Sunday (UK)", {"UK"}, "4th Sunday of Lent (3 weeks before Easter)", lambda y: easter(y) - timedelta(21), 21, "flowers, jewellery, beauty, gifts"),
    ("uk_good_friday", "Good Friday bank holiday", {"UK"}, "2 days before Easter", lambda y: easter(y) - timedelta(2), 7, "Easter weekend sales, garden, DIY"),
    ("uk_easter_monday", "Easter Monday bank holiday", {"UK"}, "day after Easter (England, Wales, NI)", lambda y: easter(y) + timedelta(1), 7, "garden, DIY, spring fashion"),
    ("uk_early_may", "Early May bank holiday", {"UK"}, "1st Monday of May", lambda y: nth_weekday(y, 5, 0, 1), 7, "garden, outdoor, spring sales"),
    ("uk_spring_bh", "Spring bank holiday", {"UK"}, "last Monday of May", lambda y: nth_weekday(y, 5, 0, -1), 7, "summer kick-off, garden, travel"),
    ("uk_summer_sales", "Summer sales (UK, typical start)", {"UK"}, "late June; most retailers start around the last week of June", lambda y: (nth_weekday(y, 6, 0, -1), "verify"), 7, "fashion clearance, home"),
    ("uk_back_to_school", "Back to school (UK)", {"UK"}, "late July to early September (England term starts early Sep)", fixed(7, 25), 28, "school uniform, shoes, bags, stationery"),
    ("uk_summer_bh", "Summer bank holiday", {"UK"}, "last Monday of August (England, Wales, NI)", lambda y: nth_weekday(y, 8, 0, -1), 7, "end-of-summer sales, back to school"),
    ("uk_bonfire", "Bonfire Night", {"UK"}, "5 November", fixed(11, 5), 10, "outerwear, home, food"),
    ("uk_christmas_bh", "Christmas Day bank holiday (observed)", {"UK"}, "25 December, or substitute weekday", lambda y: uk_christmas_pair(y)[0], 7, "store hours and delivery planning"),
    ("uk_boxing_day", "Boxing Day (sales start)", {"UK"}, "26 December (bank holiday may be substituted)", fixed(12, 26), 7, "biggest UK sale day; fashion, home, electronics"),
    ("uk_boxing_bh", "Boxing Day bank holiday (observed)", {"UK"}, "26 December, or substitute weekday", lambda y: uk_christmas_pair(y)[1], 7, "store hours and delivery planning"),

    # EU-wide and country moments
    ("eu_epiphany", "Epiphany / Three Kings (ES Reyes, IT Befana)", {"ES", "IT"}, "6 January", fixed(1, 6), 21, "ES: the main gift day; IT: kids, sweets"),
    ("fr_winter_sales", "Winter sales start (FR soldes)", {"FR"}, "2nd Wednesday of January, or 1st if the 2nd is after the 12th (some departments differ)", fr_winter_sales, 7, "fashion, home clearance"),
    ("eu_carnival", "Carnival / Rosenmontag (DE)", {"DE", "NL", "IT", "ES"}, "Monday 48 days before Easter", lambda y: easter(y) - timedelta(48), 14, "costumes, party, beauty"),
    ("es_it_fathers", "Father's Day (ES, IT)", {"ES", "IT"}, "19 March (St Joseph)", fixed(3, 19), 21, "menswear, grooming, gifts"),
    ("nl_kings_day", "King's Day (NL)", {"NL"}, "27 April, or 26 April when the 27th is a Sunday", nl_kings_day, 14, "orange apparel, party, outdoor"),
    ("eu_may_day", "Labour Day (most of EU)", {"EU"}, "1 May", fixed(5, 1), 7, "long weekend, spring sales"),
    ("es_mothers", "Mother's Day (ES)", {"ES"}, "1st Sunday of May", lambda y: nth_weekday(y, 5, 6, 1), 21, "jewellery, beauty, gifts"),
    ("de_vatertag", "Ascension Day / Vatertag (DE)", {"DE", "EU"}, "39 days after Easter (public holiday in DE, FR, NL and others)", lambda y: easter(y) + timedelta(39), 14, "DE: menswear, outdoor, BBQ; elsewhere a long weekend"),
    ("fr_mothers", "Fête des Mères (FR)", {"FR"}, "last Sunday of May, or 1st Sunday of June if that clashes with Pentecost", fr_mothers_day, 21, "jewellery, beauty, gifts"),
    ("eu_whit_monday", "Whit Monday", {"DE", "FR", "NL"}, "50 days after Easter", lambda y: easter(y) + timedelta(50), 7, "long weekend, garden, travel"),
    ("fr_summer_sales", "Summer sales start (FR soldes)", {"FR"}, "last Wednesday of June, or the one before if after the 28th (some departments differ)", fr_summer_sales, 7, "fashion, home clearance"),
    ("es_summer_sales", "Summer sales (ES, typical start)", {"ES"}, "1 July by custom (deregulated; many start earlier)", lambda y: (date(y, 7, 1), "verify"), 7, "fashion clearance"),
    ("fr_bastille", "Bastille Day (FR)", {"FR"}, "14 July", fixed(7, 14), 7, "summer sales week, travel"),
    ("eu_rentree", "Back to school (FR rentrée, DE/NL vary by region)", {"FR", "DE", "NL", "EU"}, "FR: about 1 September; DE/NL: staggered by region, August to September", lambda y: (date(y, 9, 1), "verify"), 28, "school supplies, kids apparel, bags, laptops"),
    ("de_unity", "German Unity Day (DE)", {"DE"}, "3 October", fixed(10, 3), 7, "long weekend, autumn sales"),
    ("eu_all_saints", "All Saints' Day", {"FR", "IT", "ES", "DE"}, "1 November (public holiday in FR, IT, ES and parts of DE)", fixed(11, 1), 7, "long weekend, autumn"),
    ("de_st_martin", "St Martin's Day (DE, NL)", {"DE", "NL"}, "11 November", fixed(11, 11), 7, "kids, lanterns, baking"),
    ("eu_first_advent", "First Sunday of Advent", {"DE", "NL", "EU"}, "4th Sunday before Christmas", first_advent, 14, "advent calendars, Christmas decor, gifting start"),
    ("nl_sinterklaas", "Sinterklaas / pakjesavond (NL)", {"NL"}, "5 December", fixed(12, 5), 28, "the main NL gift day: toys, gifts"),
    ("de_nikolaus", "Nikolaustag (DE)", {"DE"}, "6 December", fixed(12, 6), 14, "small gifts, sweets, kids"),
]


def resolve(fn, year):
    out = fn(year)
    if isinstance(out, tuple):
        return out
    return out, "computed"


def selected(markets, moment_markets):
    tags = set()
    for m in markets:
        if m == "EU":
            tags |= {"EU"} | EU_COUNTRIES
        else:
            tags.add(m)
        if m in EU_COUNTRIES:
            tags.add("EU")
    tags.add("GLOBAL")
    return bool(tags & moment_markets)


def build(markets, years, start, end):
    rows = []
    for year in years:
        for mid, name, mk, rule, fn, lead, cats in M:
            if not selected(markets, mk):
                continue
            d, status = resolve(fn, year)
            if d is None:
                # No date to test against the window: keep it only for a year the window covers.
                if start and end and not start.year <= year <= end.year:
                    continue
                rows.append({"id": mid, "name": name, "markets": sorted(mk), "rule": rule, "year": year,
                             "date": None, "promote_from": None, "status": status,
                             "lead_days": lead, "categories": cats})
                continue
            promo = d - timedelta(lead)
            if start and end and not (start <= d <= end or start <= promo <= end):
                continue
            rows.append({"id": mid, "name": name, "markets": sorted(mk), "rule": rule, "year": year,
                         "date": d.isoformat(), "promote_from": promo.isoformat(), "status": status,
                         "lead_days": lead, "categories": cats})
    rows.sort(key=lambda r: (r["date"] or f"{r['year']}-99"))
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--market", default="US,UK,EU", help="comma-separated market codes (default US,UK,EU)")
    p.add_argument("--year", type=int, action="append", help="year(s); repeatable. Default: years covered by the window, or this year")
    p.add_argument("--from", dest="start", help="window start, YYYY-MM-DD")
    p.add_argument("--to", dest="end", help="window end, YYYY-MM-DD")
    p.add_argument("--weeks", type=int, help="window length in weeks from --from (instead of --to)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--out", help="write the output to this file instead of printing it (for clients that refuse shell redirects)")
    a = p.parse_args()
    if a.out:
        sys.stdout = open(a.out, "w", encoding="utf-8")

    markets = [m.strip().upper() for m in a.market.split(",") if m.strip()]
    markets = ["UK" if m == "GB" else m for m in markets]
    unknown = [m for m in markets if m not in KNOWN_MARKETS]

    start = date.fromisoformat(a.start) if a.start else None
    end = date.fromisoformat(a.end) if a.end else None
    if start and a.weeks and not end:
        end = start + timedelta(weeks=a.weeks)
    if start and not end:
        end = start + timedelta(weeks=8)
    if a.year:
        years = sorted(set(a.year))
    elif start:
        # include next year too, so early-next-year moments with long lead times are caught
        years = list(range(start.year, end.year + 2))
    else:
        years = [date.today().year]

    rows = build(markets, years, start, end)
    notes = []
    for m in unknown:
        notes.append(f"No section for market '{m}' yet: showing Global moments only. Add local public "
                     f"holidays and shopping moments (look them up, label them 'unverified', and ask the user), "
                     f"and consider contributing a '{m}' section to references/retail-calendar.md and this script.")
    if any(r["status"] == "look up" for r in rows):
        notes.append("Some lunar or announced dates are not in the lookup table for this year: look them up and add them.")

    if a.json:
        print(json.dumps({"markets": markets, "window": [start and start.isoformat(), end and end.isoformat()],
                          "unknown_markets": unknown, "notes": notes, "moments": rows}, indent=2))
        return

    title = ", ".join(markets)
    win = f" | window {start} to {end}" if start else ""
    print(f"## Retail moments: {title}{win}\n")
    print("| Date | Moment | Markets | Promote from | Status | Rule | Suits |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['date'] or str(r['year']) + ' ?'} | {r['name']} | {'/'.join(r['markets'])} | "
              f"{r['promote_from'] or '-'} | {r['status']} | {r['rule']} | {r['categories']} |")
    for n in notes:
        print(f"\n> {n}")


if __name__ == "__main__":
    sys.exit(main())
