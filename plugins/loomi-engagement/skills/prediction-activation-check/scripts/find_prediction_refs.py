#!/usr/bin/env python3
"""Find which saved Engagement definitions reference each prediction.

Standard library only, no network. It only searches JSON the assistant has
already fetched with Loomi Connect.

Usage:
    python3 find_prediction_refs.py predictions.json definitions/

predictions.json: a list of objects, each with "name" and at least one of
"id" (the prediction ID) and "attribute" (its output customer attribute),
plus optional "also" (a list of other names to follow, such as an expression
or aggregate built on the score). Example:

    [{"name": "Churn risk", "id": "abc123", "attribute": "churn_probability"}]

definitions/: one JSON file per fetched object, named <type>_<id>.json, for
example scenario_<id>.json, segmentation_<id>.json, email_<id>.json,
sms_<id>.json, banner_<id>.json, report_<id>.json, dashboard_<id>.json,
filter_<id>.json, aggregate_<id>.json, expression_<id>.json. A file may hold
the raw tool response; the script looks for "name" and "status" anywhere near
the top of it.

Matching is on whole JSON string values (exact match) and, for attribute
names, also inside longer strings such as expression formulas.

If any saved file is a Loomi Connect error ("success": false), the script
stops with exit code 1 rather than report "no references found".
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def check_error(doc, name):
    for o in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            sys.exit(f"{name}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")


def unwrap(doc):
    """Strip the {"result": {...}} and {"data": {...}} wrappers."""
    for key in ("result", "data"):
        if isinstance(doc, dict) and isinstance(doc.get(key), dict):
            doc = doc[key]
    return doc


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def matches(values, needle, substring):
    for s in values:
        if s == needle or (substring and len(needle) >= 4 and needle in s):
            return True
    return False


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    if len(argv) == 2 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) != 3:
        print(__doc__)
        return 2
    preds = json.loads(Path(argv[1]).read_text())
    check_error(preds, argv[1])
    if isinstance(preds, dict):
        preds = [preds]
    defs = []
    for path in sorted(Path(argv[2]).glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            print(f"skipped {path.name}: {exc}", file=sys.stderr)
            continue
        check_error(doc, str(path))
        doc = unwrap(doc)
        kind = path.stem.split("_", 1)[0]
        name = doc.get("name", path.stem) if isinstance(doc, dict) else path.stem
        status = doc.get("status") if isinstance(doc, dict) else None
        used_by = doc.get("used_by") if isinstance(doc, dict) else None
        defs.append((kind, name, status, used_by, list(strings(doc))))

    print(f"Checked {len(defs)} definitions against {len(preds)} predictions.\n")
    for p in preds:
        needles = []
        if p.get("id"):
            needles.append((p["id"], False))
        if p.get("attribute"):
            needles.append((p["attribute"], True))
        for extra in p.get("also", []):
            needles.append((extra, True))
        hits = defaultdict(list)
        for kind, name, status, used_by, values in defs:
            if any(matches(values, n, sub) for n, sub in needles):
                label = name + (f" [{status}]" if status else "")
                if used_by:
                    label += f" used_by={','.join(used_by)}"
                hits[kind].append(label)
        print(f"## {p.get('name', p.get('id'))}")
        if not hits:
            print("  no references found")
        for kind in sorted(hits):
            for label in hits[kind]:
                print(f"  {kind}: {label}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
