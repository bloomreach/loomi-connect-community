#!/usr/bin/env python3
"""Translate a saved Bloomreach Engagement customer filter into an EQL customer condition.

For the segment builder skill's "Sizing an existing customer filter". Reads JSON the
assistant has already fetched with Loomi Connect. It never calls the network and
never runs the query. Standard library only.

Usage:
    python3 <this skill's folder>/scripts/filter_to_eql.py FILTER_JSON [--node ID] [--with-total] [--by PROPERTY] [--out FILE]

FILTER_JSON   a saved customer filter ({"filters": [...], "formula": "F0&!F1"}), a saved
              scenario condition node holding one in `customer_filter`, or a whole saved
              `search_scenarios` response (then pick the condition with --node, unless
              there is only one).
--node        the condition node's id, when FILTER_JSON is a whole scenario.
--with-total  also count everyone, so the result can be given as a share of all customers.
--by          the low-cardinality customer property the count query breaks down by
              (default: country). Every row must be added up, including null and other.
--out         write the JSON here instead of printing it.

Prints JSON: {"eql", "unsupported", "query"}.
- eql: the `customers matching` condition, or null when the filter lets everyone through
  (no rules, or formula empty or "1") or can't be counted.
- unsupported: why it can't be counted in EQL (segments, predictions, aggregates,
  expressions, calculations, some event rules, some comparisons, some rules, its custom
  formula). When it isn't empty, don't size the rest on its own: that overstates the audience.
- query: the aggregate count query to check with estimate_eql_cost before running, or
  null when it can't be counted.

The rules and EQL text match loomi-connect-openui's filterEql; a contract fixture in
tests/fixtures/engagement/segment_builder/contract/ keeps the two in step.
"""
import argparse
import json
import math
import re
import sys
from decimal import Decimal

MISSING = object()  # a key that isn't there (JavaScript's undefined)

# Rule kinds EQL can't express (they refer to saved Engagement definitions by id), in words.
UNCOUNTABLE = {
    "segmentation": "segments",
    "prediction": "predictions",
    "aggregate": "aggregates",
    "expression": "expressions",
    "embedded_aggregate": "calculations",
}
NUMBER_OPS = {"equal to": "=", "does not equal": "!=", "greater than": ">", "greater than or equal to": ">=",
              "less than": "<", "less than or equal to": "<="}
STRING_OPS = {"equals": "=", "does not equal": "!=", "contains": "contains", "does not contain": "does not contain",
              "starts with": "starts with", "ends with": "ends with"}
UNITS = {"hours", "days", "weeks", "months"}
DEFAULT_BY = "country"

# JavaScript's whitespace (String.prototype.trim and \s), so odd values give the app's text.
JS_SPACE = "\t\n\v\f\r              " \
           "    　﻿"
FORMULA_OK = re.compile("[F0-9&|!()" + JS_SPACE + "]+")
ATOM_REF = re.compile(r"F([0-9]+)")
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
RADIX = {"0x": 16, "0o": 8, "0b": 2}
PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class InputError(Exception):
    pass


# ---- JavaScript coercions (filterEql runs in JavaScript) ----

def js_trim(s):
    return s.strip(JS_SPACE)


def js_truthy(v):
    if v is MISSING or v is None or v is False or v == "":
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0 and not (isinstance(v, float) and math.isnan(v))
    return True


def js_num_str(x):
    """String(number) in JavaScript."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    d = Decimal(repr(abs(x))).normalize()
    _, digits, exp = d.as_tuple()
    ds = "".join(map(str, digits))
    k = len(ds)
    n = k + exp  # value = 0.ds × 10^n
    if k <= n <= 21:
        out = ds + "0" * (n - k)
    elif 0 < n <= 21:
        out = ds[:n] + "." + ds[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + ds
    else:
        e = n - 1
        out = (ds if k == 1 else ds[0] + "." + ds[1:]) + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + out


def to_float(v):
    try:
        return float(v)
    except OverflowError:
        return math.inf if v > 0 else -math.inf


def js_str(v):
    """String(v) in JavaScript, with null and undefined as "" (filterEql's str())."""
    if v is MISSING or v is None:
        return ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return js_num_str(to_float(v))
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return ",".join(js_str(x) for x in v)
    return "[object Object]"


def js_number(v):
    """Number(v) in JavaScript."""
    if v is MISSING:
        return math.nan
    if v is None or v is False:
        return 0.0
    if v is True:
        return 1.0
    if isinstance(v, (int, float)):
        return to_float(v)
    if isinstance(v, dict):
        return math.nan
    s = js_trim(js_str(v))
    if s == "":
        return 0.0
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    if DECIMAL.fullmatch(s):
        return float(s)
    base = RADIX.get(s[:2].lower())
    if base:
        try:
            return float(int(s[2:], base))
        except ValueError:
            return math.nan
    return math.nan


def raw(v):
    return v if isinstance(v, dict) else {}


def get(d, key):
    return d.get(key, MISSING) if isinstance(d, dict) else MISSING


# ---- the translation (same rules and text as filterEql) ----

def eql_quote(s):
    """A name or value in double quotes, with any " or \\ removed so it can't break out."""
    return '"' + js_trim(re.sub(r'["\\]', "", s)) + '"'


def name(v):
    return eql_quote(js_str(v))


def first_value(c):
    ops = get(c, "operands")
    if isinstance(ops, list) and ops and isinstance(ops[0], dict):
        return get(ops[0], "value")
    return get(c, "value")


def comparison(c):
    """One comparison in EQL (`= "x"`, `> 3`, `has value`, `more than 30 days ago`), or None."""
    op = js_str(get(c, "operator"))
    if op in ("has value", "is set"):
        return "has value"
    if op in ("has no value", "is not set"):
        return "has no value"
    v = first_value(c)
    kind = get(c, "type")
    if kind == "string":
        if op in STRING_OPS and not (v is None or isinstance(v, (dict, list))):
            return f"{STRING_OPS[op]} {eql_quote(js_str(v))}"
        return None
    if kind == "number":
        n = js_number(v)
        if op in NUMBER_OPS and js_trim(js_str(v)) != "" and math.isfinite(n):
            return f"{NUMBER_OPS[op]} {js_num_str(n)}"
        return None
    if kind == "boolean":
        if op == "is":
            return "= false" if js_str(get(c, "value")) == "false" else "= true"
        return None
    if kind == "date":
        amount = js_number(get(c, "amount"))
        units = js_str(get(c, "units"))
        if op not in ("more than", "less than") or not math.isfinite(amount) or units not in UNITS:
            return None
        tense = "ahead" if get(c, "tense") == "ahead" else "ago"
        return f"{op} {js_num_str(amount)} {units} {tense}"
    return None


def where(flt):
    """An event's "where" rules (all must hold), "" for none, or None when one can't be written."""
    parts = []
    for f in [x for x in flt if isinstance(x, dict)] if isinstance(flt, list) else []:
        a = raw(get(f, "attribute"))
        c = get(f, "constraint")
        cmp = comparison(c) if isinstance(c, dict) else None
        if get(a, "type") != "property" or not cmp:
            return None
        parts.append(f".{name(get(a, 'property'))} {cmp}")
    return " where " + " and ".join(parts) if parts else ""


def window(d):
    """' in last 30 days' for a relative window, '' for all time, None for windows EQL can't take here."""
    if not isinstance(d, dict) or not js_truthy(get(d, "enabled")):
        return ""
    dur = raw(get(d, "duration"))
    count = js_number(get(dur, "count"))
    if js_truthy(get(d, "absolute")) or js_str(get(dur, "units")) not in UNITS or not js_truthy(count):
        return None
    return f" in last {js_num_str(count)} {js_str(get(dur, 'units'))}"


def atom_eql(atom):
    """One rule as ("eql", text) or ("reason", why it can't be counted)."""
    if get(atom, "type") == "funnel_steps":
        steps = get(atom, "steps")
        steps = [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []
        span = window(get(atom, "date_filter"))
        written = []
        for s in steps:
            w = where(get(s, "filter"))
            written.append(None if w is None or not js_str(get(s, "type")) else f"{name(get(s, 'type'))}{w}")
        if not steps or span is None or any(w is None for w in written):
            return ("reason", "some event rules")
        if len(written) == 1:
            return ("eql", f"exists[event {written[0]}{span}]")
        return ("eql", f"funnel({' followed by '.join(written)}{span})")
    a = raw(get(atom, "attribute"))
    c = raw(get(atom, "constraint"))
    kind = js_str(get(a, "type"))
    if kind in UNCOUNTABLE:
        return ("reason", UNCOUNTABLE[kind])
    if get(a, "type") == "consent":
        yes = f"has consent {name(get(a, 'category'))}"
        return ("eql", f"not {yes}" if js_str(get(c, "value")) == "false" else yes)
    cmp = comparison(c)
    if not cmp:
        return ("reason", "some comparisons")
    if get(a, "type") == "property":
        return ("eql", f"customer.{name(get(a, 'property'))} {cmp}")
    if get(a, "type") == "id":
        return ("eql", f"id {name(get(a, 'id'))} {cmp}")
    return ("reason", "some rules")


def filter_eql(flt):
    """The whole filter as one EQL condition (its F0 & !F1 | F2 formula kept), or what stops it being counted."""
    atoms = get(flt, "filters")
    atoms = [a for a in atoms if isinstance(a, dict)] if isinstance(atoms, list) else []
    formula = js_trim(js_str(get(flt, "formula")))
    if not atoms or not formula or formula == "1":
        return {"eql": None, "unsupported": []}
    written = [atom_eql(a) for a in atoms]
    unsupported = list(dict.fromkeys(why for kind, why in written if kind == "reason"))
    if unsupported:
        return {"eql": None, "unsupported": unsupported}
    # Only F-numbers, operators and brackets may pass through; anything else isn't a formula Engagement wrote.
    if not FORMULA_OK.fullmatch(formula):
        return {"eql": None, "unsupported": ["its custom formula"]}

    def atom_ref(m):
        digits = m.group(1).lstrip("0") or "0"
        i = int(digits) if len(digits) < 16 else len(written)
        return f"({written[i][1]})" if i < len(written) else "(false)"

    # Operators first, so a rule's own `!=` or a value's `&` isn't rewritten.
    eql = ATOM_REF.sub(atom_ref, formula.replace("&", " and ").replace("|", " or ").replace("!", " not "))
    return {"eql": eql, "unsupported": []}


def count_query(eql, with_total, by=DEFAULT_BY):
    """The aggregate count. With the total, the second column counts everyone (the app's form)."""
    group = f"by customer.{by if PLAIN_NAME.fullmatch(by) else eql_quote(by)} grouping top 1 with null"
    if with_total:
        return f"select count customers{f' matching {eql}' if eql else ''}, count customers {group}"
    return f"select count customers {group}{f' customers matching {eql}' if eql else ''}"


def translate(flt, with_total=False, by=DEFAULT_BY):
    out = filter_eql(flt)
    out["query"] = None if out["unsupported"] else count_query(out["eql"], with_total, by)
    return out


# ---- reading the saved tool result ----

def unwrap(obj):
    """Strip the {result: {data: ...}} / {data: ...} envelopes Loomi Connect uses."""
    for _ in range(3):
        for o in (obj, obj.get("result") if isinstance(obj, dict) else None):
            if isinstance(o, dict) and o.get("success") is False:
                raise InputError(f"Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                                 "Fetch the filter again; don't treat this as an empty filter.")
        if isinstance(obj, dict) and isinstance(obj.get("result"), dict):
            obj = obj["result"]
        if isinstance(obj, dict) and obj.get("data") is not None:
            obj = obj["data"]
    return obj


def find_filter(obj, node_id=None):
    """The customer filter in a saved filter, condition node or whole scenario."""
    obj = unwrap(obj)
    if isinstance(obj, list) and len(obj) == 1:
        obj = obj[0]
    if not isinstance(obj, dict):
        raise InputError("expected a customer filter, a condition node or a scenario (a JSON object)")
    if "nodes" in obj and isinstance(obj["nodes"], list):
        conditions = [n for n in obj["nodes"] if isinstance(n, dict) and "customer_filter" in n]
        if node_id is not None:
            conditions = [n for n in conditions if str(n.get("id")) == str(node_id)]
            if not conditions:
                raise InputError(f"no node {node_id} with a customer filter in this scenario")
        if len(conditions) != 1:
            ids = ", ".join(str(n.get("id")) for n in conditions) or "none"
            raise InputError(f"pick one condition with --node (nodes with a customer filter: {ids})")
        obj = conditions[0]
    if "customer_filter" in obj:
        obj = obj["customer_filter"]
    if not isinstance(obj, dict) or not ("filters" in obj or "formula" in obj):
        raise InputError("no customer filter found (expected `filters` and `formula`)")
    return obj


def main():
    p = argparse.ArgumentParser(description="Translate a saved Engagement customer filter into EQL.")
    p.add_argument("filter_json", help="saved customer filter, condition node or scenario JSON")
    p.add_argument("--node", help="condition node id, when the file is a whole scenario")
    p.add_argument("--with-total", action="store_true", help="also count everyone, for a share of all customers")
    p.add_argument("--by", default=DEFAULT_BY, help="customer property the count query breaks down by")
    p.add_argument("--out", help="write the JSON here instead of printing it")
    args = p.parse_args()
    with open(args.filter_json, encoding="utf-8") as f:
        flt = find_filter(json.load(f), args.node)
    text = json.dumps(translate(flt, args.with_total, args.by), indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    try:
        main()
    except InputError as e:
        sys.exit(f"error: {e}")
    except (OSError, ValueError) as e:
        sys.exit(f"error: {e}")
