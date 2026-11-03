#!/usr/bin/env python3
"""Build an access-review table from saved list_project_users responses.

Standard library only. No network access. It reads JSON responses the
assistant has already saved from the Loomi Connect `list_project_users` tool
(one file per project) and prints a Markdown access-review table plus the
flags the skill reports. It never changes anything.

Usage:
    python3 access_review.py --company-domain example.com \
        [--company-domain example.co.uk] [--vendor-domain partner.example] \
        [--many-projects 3] "Project A=users_a.json" "Project B=users_b.json"

Each positional argument is "<project label>=<file>". A bare file path uses
the file name as the label.

Fields read from each user record: _id, email, username, first_name,
last_name, role. Nothing else is assumed to exist.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone

GENERIC_LOCAL = re.compile(
    r"^(admin|administrator|api|app|automation|bot|crm|data|demo|dev|developer|"
    r"digital|ecom|ecommerce|email|emails|hello|info|integration|integrations|"
    r"it|mail|marketing|news|newsletter|no-?reply|ops|qa|sales|sandbox|service|"
    r"shared|support|sysadmin|team|tech|test|testing|tester|user|web|webmaster)"
    r"(\d*|[._-]\d+|\+.*)$",  # marketing@, test1@, qa_2@, api+x@; not dev.patel@
    re.I,
)
TEST_WORD = re.compile(r"(test|qa|dev|demo|sandbox|tmp|temp|dummy)\d*", re.I)
NAME_LIKE = {"dev"}  # also a given name: "dev.patel" is a person


def looks_like_test(local):
    tokens = [t for t in re.split(r"[._+-]", local) if t]
    if not tokens:
        return False
    first_counts = len(tokens) == 1 or tokens[0].lower() not in NAME_LIKE
    return any(TEST_WORD.fullmatch(t) for t in (tokens if first_counts else tokens[1:]))


def unwrap(obj, path):
    """Return the list of user records from a list_project_users response."""
    for o in (obj, obj.get("result") if isinstance(obj, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    for key in ("result", "data"):
        if isinstance(obj, dict) and key in obj:
            obj = obj[key]
    if isinstance(obj, dict):
        for key in ("users", "items"):
            if key in obj:
                obj = obj[key]
    return [u for u in obj if isinstance(u, dict)] if isinstance(obj, list) else []


def id_created(user_id):
    """Approximate account creation date, inferred from a 24-hex-char object ID.

    This is an inference, not a field the tool returns. Returns None if the ID
    doesn't look like an object ID.
    """
    if not isinstance(user_id, str) or not re.fullmatch(r"[0-9a-fA-F]{24}", user_id):
        return None
    ts = int(user_id[:8], 16)
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def classify_domain(domain, company, vendor):
    def match(d, roots):
        return any(d == r or d.endswith("." + r) for r in roots)
    if not domain:
        return "unknown"
    if match(domain, company):
        return "company"
    if match(domain, vendor):
        return "vendor"
    return "external"


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help='"<project label>=<file>" or a file path')
    p.add_argument("--company-domain", action="append", default=[], help="your organisation's email domain (repeatable)")
    p.add_argument("--vendor-domain", action="append", default=[], help="known vendor or agency domain (repeatable)")
    p.add_argument("--many-projects", type=int, default=3,
                   help="flag users in at least this many projects (default 3, or every project when fewer are reviewed)")
    p.add_argument("--show-created", action="store_true", help="add the inferred account-creation date column")
    args = p.parse_args()

    company = [d.lower().lstrip("@") for d in args.company_domain]
    vendor = [d.lower().lstrip("@") for d in args.vendor_domain]
    if not company:
        print("Note: no --company-domain given, so every domain is reported as external.", file=sys.stderr)

    users = {}      # email -> merged record
    project_order = []
    for spec in args.files:
        label, sep, path = spec.partition("=")
        if not sep:
            label, path = spec, spec
        project_order.append(label)
        with open(path, encoding="utf-8") as fh:
            records = unwrap(json.load(fh), path)
        for r in records:
            email = (r.get("email") or r.get("username") or "").strip().lower()
            if not email:
                continue
            u = users.setdefault(email, {"email": email, "projects": {}, "first": r.get("first_name"),
                                          "last": r.get("last_name"), "id": r.get("_id")})
            u["projects"][label] = r.get("role") or "(no role)"

    many = max(2, min(args.many_projects, len(project_order)))  # works with fewer projects than the threshold
    rows, flags = [], {"external": [], "vendor": [], "unknown": [], "generic": [], "test": [],
                       "incomplete": [], "many": []}
    for email in sorted(users):
        u = users[email]
        local, _, domain = email.partition("@")
        dclass = classify_domain(domain, company, vendor)
        notes = []
        if dclass in ("external", "vendor", "unknown"):
            flags[dclass].append(email)
            notes.append(dclass)
        if GENERIC_LOCAL.match(local):
            flags["generic"].append(email)
            notes.append("generic")
        elif looks_like_test(local) or "+" in local:
            flags["test"].append(email)
            notes.append("test/alias")
        first, last = (u["first"] or "").strip(), (u["last"] or "").strip()
        if not first or not last or "@" in first or "@" in last:
            flags["incomplete"].append(email)
            notes.append("no name")
        n = len(u["projects"])
        if len(project_order) > 1 and n >= many:
            flags["many"].append(email)
            notes.append(f"{n} projects")
        roles = sorted(set(u["projects"].values()))
        created = id_created(u["id"]) if args.show_created else None
        rows.append((email, dclass, ", ".join(roles), n, created, "; ".join(notes)))

    header = ["Email", "Domain", "Role(s)", "Projects"] + (["Account created (inferred)"] if args.show_created else []) + ["Flags"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for email, dclass, roles, n, created, notes in rows:
        cells = [email, dclass, roles, str(n)] + ([str(created or "?")] if args.show_created else []) + [notes or "-"]
        print("| " + " | ".join(cells) + " |")

    print()
    print(f"Projects reviewed: {len(project_order)}; distinct users: {len(users)}")
    role_counts = {}
    for u in users.values():
        for role in u["projects"].values():
            role_counts[role] = role_counts.get(role, 0) + 1
    print("Role labels (user-project pairs): " + ", ".join(f"{k} {v}" for k, v in sorted(role_counts.items(), key=lambda kv: -kv[1])))
    if len(project_order) > 1:
        print()
        print("| Project | Users | Company | Vendor | External | Generic or test |")
        print("|---|---|---|---|---|---|")
        for label in project_order:
            members = [e for e, u in users.items() if label in u["projects"]]
            def count(kind):
                return sum(1 for e in members if classify_domain(e.partition("@")[2], company, vendor) == kind)
            gen = sum(1 for e in members if e in flags["generic"] or e in flags["test"])
            print(f"| {label} | {len(members)} | {count('company')} | {count('vendor')} | {count('external')} | {gen} |")
    print()
    for key, title in [("external", "External domains"), ("vendor", "Vendor domains"),
                       ("generic", "Shared or generic accounts"), ("test", "Test or alias accounts"),
                       ("incomplete", "No first or last name"),
                       ("many", f"In {many}+ projects")]:
        print(f"{title}: {len(flags[key])}")


if __name__ == "__main__":
    main()
