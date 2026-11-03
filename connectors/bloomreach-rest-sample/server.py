#!/usr/bin/env python3
"""Sample MCP server for a few of Bloomreach's public REST APIs. For testing skills, not production.

It speaks MCP over stdio (newline-delimited JSON-RPC) and offers four read-only tools:

  discovery_search          Product and Category Search API   (core.dxpapi.com)
  discovery_autosuggest     Autosuggest API                   (suggest.dxpapi.com)
  engagement_list_imports   Imports Management API, list      (GET, private access)
  engagement_get_import     Imports Management API, one       (GET, private access)

Keys come only from environment variables (see README.md). They are never accepted as tool
arguments, and never appear in tool results, error messages or logs: results are redacted and
scrubbed of every configured secret value before they're returned.

Standard library only. Requests go only to the documented hosts over https, GET only, without
following redirects, with a timeout and a response size cap.
"""
import base64
import ipaddress
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

NAME, VERSION = "bloomreach-rest-sample", "0.1.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
DISCOVERY_SEARCH = "https://core.dxpapi.com/api/v1/core/"
DISCOVERY_SUGGEST = "https://suggest.dxpapi.com/api/v2/suggest/"
ENGAGEMENT_DEFAULT = "https://api.exponea.com"
ENGAGEMENT_DOMAINS = ("exponea.com", "bloomreach.com")
# The documented default for _br_uid_2 in the API reference; server-side calls have no pixel cookie.
SAMPLE_BR_UID = "uid%3D7797686432023%3Av%3D11.5%3Ats%3D1428617911187%3Ahc%3D55"
TIMEOUT_S = 20
MAX_RESPONSE_BYTES = 2_000_000
MAX_RESULT_CHARS = 200_000
MAX_ROWS = 50
SECRET_ENV = ("BLOOMREACH_DISCOVERY_AUTH_KEY", "BLOOMREACH_ENGAGEMENT_API_KEY_ID", "BLOOMREACH_ENGAGEMENT_API_SECRET")
# Field names whose values are credentials wherever they appear in a response (import sources carry the
# username and password, or a connection string, for the system they import from).
SECRET_WORDS = {"password", "passwd", "pwd", "pass", "secret", "token", "credential", "credentials", "sas",
                "authorization", "auth", "apikey", "passphrase"}
SECRET_PHRASES = ("auth_key", "api_key", "access_key", "private_key", "client_secret", "connection_string",
                  "conn_string", "connectionstring", "secret_key")
SECRET_PARAMS = re.compile(r"([?&;](?:[^=&;#]*(?:key|token|secret|sig|signature|password|pwd|auth|credential)[^=&;#]*)=)[^&;#]*", re.I)
USERINFO = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^/\s@]+@", re.I)
NAME_FIELDS = ("name", "key", "header", "field")


class ToolError(Exception):
    """A problem to report to the assistant as a tool error (never contains a secret)."""


def env(name, required_for=None):
    value = os.environ.get(name, "").strip()
    if not value and required_for:
        raise ToolError(f"{required_for} needs the {name} environment variable. Set it in this server's "
                        "configuration in your MCP client (see connectors/bloomreach-rest-sample/README.md). "
                        "Don't paste the value into the chat.")
    return value


def scrub(text):
    """Replace every configured secret, in every form it could take in a response or error: raw, URL-encoded,
    JSON-escaped, and the Basic-auth header built from the Engagement key pair."""
    raw = [os.environ.get(n, "").strip() for n in SECRET_ENV]
    if raw[1] and raw[2]:
        raw.append(base64.b64encode(f"{raw[1]}:{raw[2]}".encode()).decode())
    forms = set()
    for s in raw:
        if len(s) >= 4:
            forms |= {s, urllib.parse.quote(s, safe=""), urllib.parse.quote_plus(s), json.dumps(s)[1:-1]}
    for f in sorted(forms, key=len, reverse=True):
        text = text.replace(f, "[redacted]")
    return text


def is_secret_name(name):
    """True for a field name like password, apiKey, clientSecret, X-Api-Key or connection_string."""
    norm = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name)).lower().replace("-", "_").strip("_")
    words = set(norm.split("_"))
    return bool(words & SECRET_WORDS) or any(p in norm for p in SECRET_PHRASES)


def clean_string(text, strip_urls):
    """Blank credentials inside a string: user info and secret-looking parameters in any URL, and the whole query
    of a URL when strip_urls is set. A string holding JSON is redacted as JSON."""
    if text[:1] == "{" and len(text) < 100_000:
        try:
            return json.dumps(redact(json.loads(text), strip_urls), ensure_ascii=False)
        except ValueError:
            pass
    text = USERINFO.sub(r"\1[redacted]@", text)
    if strip_urls and re.match(r"[a-z][a-z0-9+.-]*://\S*\?", text, re.I):
        return text.split("?", 1)[0] + "?[query redacted]"
    return SECRET_PARAMS.sub(r"\1[redacted]", text)


def redact(obj, strip_urls=False):
    """Copy of a JSON value with credentials blanked: fields with credential names, {"name": "X-Api-Key",
    "value": ...} pairs, user info and secret parameters in URLs, and (with strip_urls) whole URL queries."""
    if isinstance(obj, dict):
        label = next((obj[f] for f in NAME_FIELDS if isinstance(obj.get(f), str)), None)
        out = {}
        for k, v in obj.items():
            if v in (None, "", [], {}):
                out[k] = v
            elif is_secret_name(k) or (label and is_secret_name(label) and k == "value"):
                out[k] = {kk: "[redacted]" for kk in v} if isinstance(v, dict) else "[redacted]"
            else:
                out[k] = redact(v, strip_urls)
        return out
    if isinstance(obj, list):
        return [redact(v, strip_urls) for v in obj]
    if isinstance(obj, str):
        return clean_string(obj, strip_urls)
    return obj


# ----------------------------------------------------------------------------------------------
# HTTP

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never resend credentials to another URL
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def loopback_override():
    """Tests point every API at a local fake server. Only http://127.0.0.1 or ::1 is accepted, and only when
    BLOOMREACH_SAMPLE_TEST_MODE=1 is also set, so a stray variable can't send real keys to a local port."""
    url = os.environ.get("BLOOMREACH_SAMPLE_LOOPBACK_URL", "").strip()
    if not url:
        return None
    if os.environ.get("BLOOMREACH_SAMPLE_TEST_MODE") != "1":
        raise ToolError("BLOOMREACH_SAMPLE_LOOPBACK_URL is for the tests only; remove it from this server's configuration.")
    p = urllib.parse.urlsplit(url)
    try:
        ok = p.scheme == "http" and ipaddress.ip_address(p.hostname or "").is_loopback
    except ValueError:
        ok = False
    if not ok:
        raise ToolError("BLOOMREACH_SAMPLE_LOOPBACK_URL must be an http://127.0.0.1 or http://[::1] address.")
    return url.rstrip("/")


def engagement_base():
    base = env("BLOOMREACH_ENGAGEMENT_BASE_URL") or ENGAGEMENT_DEFAULT
    p = urllib.parse.urlsplit(base)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query:
        raise ToolError("BLOOMREACH_ENGAGEMENT_BASE_URL must be a plain https:// URL, such as https://api.exponea.com.")
    if not any(p.hostname == d or p.hostname.endswith("." + d) for d in ENGAGEMENT_DOMAINS):
        raise ToolError("BLOOMREACH_ENGAGEMENT_BASE_URL must be a Bloomreach API host (" + ", ".join(
            "*." + d for d in ENGAGEMENT_DOMAINS) + "). If your instance's API URL is elsewhere, check it in Project "
            "settings > Access management > API, then add its domain to ENGAGEMENT_DOMAINS in server.py.")
    return base.rstrip("/")


def get_json(url, params=None, headers=None):
    override = loopback_override()
    if override:
        p = urllib.parse.urlsplit(url)
        url = override + "/" + p.hostname + p.path
    elif not url.startswith("https://"):
        raise ToolError("Refusing a non-https request.")
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")}, doseq=True)
    req = urllib.request.Request(url, method="GET", headers=dict(headers or {}, Accept="application/json",
                                                                 **{"User-Agent": f"{NAME}/{VERSION}"}))
    try:
        with OPENER.open(req, timeout=TIMEOUT_S) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise ToolError(f"The API answered with a redirect (HTTP {e.code}), which this server doesn't follow.")
        # Scrub before cutting, so a secret split by the cut can't slip through.
        detail = clean_string(scrub(e.read(5000).decode("utf-8", "replace")), True) if e.fp else ""
        raise ToolError(f"The API returned HTTP {e.code}. {detail[:500]}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ToolError(scrub(f"Couldn't reach the API: {getattr(e, 'reason', e)}"))
    if len(body) > MAX_RESPONSE_BYTES:
        raise ToolError(f"The response is over {MAX_RESPONSE_BYTES // 1_000_000} MB. Ask for fewer rows or fields.")
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise ToolError("The API didn't return JSON: " + scrub(body[:5000].decode("utf-8", "replace"))[:200])


# ----------------------------------------------------------------------------------------------
# Tools

def request_id():
    return str(random.randint(10 ** 12, 10 ** 13 - 1))


def discovery_common(tool):
    site = env("BLOOMREACH_DISCOVERY_SITE_URL") or "https://www.example.com/"
    return {"account_id": env("BLOOMREACH_DISCOVERY_ACCOUNT_ID", tool), "_br_uid_2": urllib.parse.unquote(SAMPLE_BR_UID),
            "url": site, "ref_url": site, "request_id": request_id()}


def rows_arg(args, default=10):
    try:
        rows = int(args.get("rows", default))
    except (TypeError, ValueError):
        raise ToolError("rows must be a whole number.")
    if not 1 <= rows <= MAX_ROWS:
        raise ToolError(f"rows must be between 1 and {MAX_ROWS}.")
    return rows


def discovery_search(args):
    q = str(args.get("q") or "").strip()
    if not q:
        raise ToolError("q is required: the search terms, or the category ID when search_type is category.")
    search_type = args.get("search_type") or "keyword"
    if search_type not in ("keyword", "category"):
        raise ToolError("search_type must be keyword or category.")
    fl = args.get("fl") or "pid,title,brand,price,sale_price,url"
    if "pid" not in [f.strip() for f in fl.split(",")]:
        fl = "pid," + fl
    params = dict(discovery_common("discovery_search"), domain_key=env("BLOOMREACH_DISCOVERY_DOMAIN_KEY", "discovery_search"),
                  auth_key=env("BLOOMREACH_DISCOVERY_AUTH_KEY"), request_type="search", search_type=search_type,
                  q=q, fl=fl, rows=rows_arg(args), start=int(args.get("start") or 0), sort=args.get("sort"),
                  view_id=args.get("view_id"), fq=list(args.get("fq") or []) or None)
    return get_json(DISCOVERY_SEARCH, params)


def discovery_autosuggest(args):
    q = str(args.get("q") or "").strip()
    if not q:
        raise ToolError("q is required: the partial query a shopper has typed.")
    domain = env("BLOOMREACH_DISCOVERY_DOMAIN_KEY", "discovery_autosuggest")
    params = dict(discovery_common("discovery_autosuggest"), request_type="suggest", q=q,
                  catalog_views=args.get("catalog_views") or domain)
    return get_json(DISCOVERY_SUGGEST, params)


def engagement_auth(tool):
    key_id = env("BLOOMREACH_ENGAGEMENT_API_KEY_ID", tool)
    secret = env("BLOOMREACH_ENGAGEMENT_API_SECRET", tool)
    token = urllib.parse.quote(env("BLOOMREACH_ENGAGEMENT_PROJECT_TOKEN", tool), safe="")
    basic = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    return token, {"Authorization": "Basic " + basic}


def engagement_list_imports(args):
    token, headers = engagement_auth("engagement_list_imports")
    try:
        limit, offset = int(args.get("limit") or 10), int(args.get("offset") or 0)
    except (TypeError, ValueError):
        raise ToolError("limit and offset must be whole numbers.")
    if not 1 <= limit <= 50 or offset < 0:
        raise ToolError("limit must be between 1 and 50, and offset 0 or more.")
    return get_json(f"{engagement_base()}/imports/v1/{token}", {"limit": limit, "offset": offset}, headers)


def engagement_get_import(args):
    import_id = str(args.get("import_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", import_id):
        raise ToolError("import_id must be an import ID from engagement_list_imports (letters, digits, - and _).")
    token, headers = engagement_auth("engagement_get_import")
    return get_json(f"{engagement_base()}/imports/v1/{token}/{import_id}", None, headers)


TOOLS = {
    "discovery_search": (discovery_search, "Run a Bloomreach Discovery product or category search through the public "
                         "Product and Category Search API, and return the results shoppers would see: products, facets, "
                         "redirects and any media in the grid. Read-only.", {
        "q": {"type": "string", "description": "Search terms, or the category ID when search_type is category."},
        "search_type": {"type": "string", "enum": ["keyword", "category"], "default": "keyword"},
        "fl": {"type": "string", "description": "Comma-separated fields to return (pid is always included).",
               "default": "pid,title,brand,price,sale_price,url"},
        "rows": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS, "default": 10},
        "start": {"type": "integer", "minimum": 0, "default": 0},
        "fq": {"type": "array", "items": {"type": "string"}, "description": "Filters, e.g. [\"brand:\\\"Acme\\\"\"]."},
        "sort": {"type": "string", "description": "e.g. \"sale_price desc\"."},
        "view_id": {"type": "string"}}, ["q"]),
    "discovery_autosuggest": (discovery_autosuggest, "Get Bloomreach Discovery autosuggestions for a partial query "
                              "through the public Autosuggest API: query, attribute and product suggestions. Read-only.", {
        "q": {"type": "string", "description": "The partial query a shopper has typed."},
        "catalog_views": {"type": "string", "description": "Catalog views (default: the domain key's product catalog)."}},
        ["q"]),
    "engagement_list_imports": (engagement_list_imports, "List the imports in the configured Bloomreach Engagement "
                                "project through the public Imports Management API. Source credentials are redacted. "
                                "Read-only.", {
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        "offset": {"type": "integer", "minimum": 0, "default": 0}}, []),
    "engagement_get_import": (engagement_get_import, "Read one import's definition from the configured Bloomreach "
                              "Engagement project through the public Imports Management API. Source credentials are "
                              "redacted. Read-only.", {
        "import_id": {"type": "string", "description": "An import_id from engagement_list_imports."}}, ["import_id"]),
}


def tool_list():
    return [{"name": n, "description": d, "annotations": {"readOnlyHint": True},
             "inputSchema": {"type": "object", "properties": p, "required": r, "additionalProperties": False}}
            for n, (_, d, p, r) in TOOLS.items()]


def call_tool(name, args):
    if name not in TOOLS:
        raise ToolError(f"Unknown tool: {name}.")
    if not isinstance(args, dict):
        raise ToolError("Arguments must be an object.")
    unknown = sorted(set(args) - set(TOOLS[name][2]))
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(unknown)}. Keys are never passed as arguments.")
    text = scrub(json.dumps(redact(TOOLS[name][0](args), strip_urls=name.startswith("engagement_")), ensure_ascii=False))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"... [cut at {MAX_RESULT_CHARS} characters; ask for fewer rows or fields]"
    return text


# ----------------------------------------------------------------------------------------------
# MCP over stdio

def handle(msg):
    try:
        return dispatch(msg)
    except Exception as e:  # a malformed request gets an error, never a traceback
        return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": f"Internal error: {type(e).__name__}"}}


def dispatch(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # a notification, such as notifications/initialized
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}}, "serverInfo": {"name": NAME, "version": VERSION},
            "instructions": "Read-only sample tools for Bloomreach public REST APIs. Keys are configured in the "
                            "environment; never ask the user for them."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            text, is_error = call_tool(params.get("name"), params.get("arguments") or {}), False
        except ToolError as e:
            text, is_error = str(e), True
        except Exception as e:  # never let a traceback (which could hold request data) reach the client
            text, is_error = scrub(f"Unexpected error: {type(e).__name__}."), True
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None,
                                                                "error": {"code": -32600, "message": "Invalid request"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
