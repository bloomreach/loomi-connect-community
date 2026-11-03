"""Tests for the sample Bloomreach REST connector (connectors/bloomreach-rest-sample/server.py).

The server runs as a subprocess speaking MCP over stdio, with every API pointed at a fake local HTTP
server through BLOOMREACH_SAMPLE_LOOPBACK_URL. Nothing reaches the network. The keys are made up.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "connectors/bloomreach-rest-sample/server.py"
KEYS = {"BLOOMREACH_DISCOVERY_ACCOUNT_ID": "1234", "BLOOMREACH_DISCOVERY_DOMAIN_KEY": "acme_store",
        "BLOOMREACH_DISCOVERY_AUTH_KEY": "disc+FAKE/auth=9f8e", "BLOOMREACH_DISCOVERY_SITE_URL": "https://shop.example.test/",
        "BLOOMREACH_ENGAGEMENT_PROJECT_TOKEN": "proj-token-0000", "BLOOMREACH_ENGAGEMENT_API_KEY_ID": "keyid-FAKE-1a2b",
        "BLOOMREACH_ENGAGEMENT_API_SECRET": "apisecret-FAKE-3c4d"}
SECRETS = [KEYS["BLOOMREACH_DISCOVERY_AUTH_KEY"], KEYS["BLOOMREACH_ENGAGEMENT_API_KEY_ID"],
           KEYS["BLOOMREACH_ENGAGEMENT_API_SECRET"],
           base64.b64encode(f"{KEYS['BLOOMREACH_ENGAGEMENT_API_KEY_ID']}:{KEYS['BLOOMREACH_ENGAGEMENT_API_SECRET']}".encode()).decode()]
# The URL-encoded forms an API might echo (the Discovery auth_key has + / = in it on purpose).
ENCODED = [urllib.parse.quote(KEYS["BLOOMREACH_DISCOVERY_AUTH_KEY"], safe=""),
           urllib.parse.quote_plus(KEYS["BLOOMREACH_DISCOVERY_AUTH_KEY"])]
IMPORT = {"import_id": "imp_1", "import_definition": {
    "name": "Nightly customers", "active": True, "trigger": {"trigger_type": "repeated"},
    "source": {"source_type": "url", "import_url": "https://files.example.test/export.csv?sig=abc123",
               "auth": {"username": "sftp-user", "password": "pa$$word"}},
    "extra": {"accessToken": "tok-FAKE-1", "clientSecret": "cs-FAKE-2", "pwd": "pwd-FAKE-3", "auth": "auth-FAKE-4",
              "connection_string": "Server=db;Password=conn-FAKE-5", "db_url": "mysql://dbuser:dbpass-FAKE-6@db.example.test/x",
              "headers": [{"name": "X-Api-Key", "value": "hdr-FAKE-7"}, {"name": "Accept", "value": "text/csv"}],
              "service_account": "{\"private_key\": \"pk-FAKE-8\", \"client_email\": \"svc@example.test\"}"}}}
LEAKS = ["pa$$word", "tok-FAKE-1", "cs-FAKE-2", "pwd-FAKE-3", "auth-FAKE-4", "conn-FAKE-5", "dbpass-FAKE-6", "hdr-FAKE-7", "pk-FAKE-8"]


class Fake(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(p.query)
        Fake.requests.append({"path": p.path, "query": q, "headers": dict(self.headers)})
        if p.path == "/core.dxpapi.com/api/v1/core/":
            qq = q.get("q", [""])[0]
            if qq == "redirect":
                return self.send(302, b"", extra={"Location": "https://evil.example.test/"})
            if qq == "huge":
                return self.send(200, b'{"x": "' + b"a" * 2_100_000 + b'"}')
            if qq == "notjson":
                return self.send(200, b"<html>oops " + KEYS["BLOOMREACH_DISCOVERY_AUTH_KEY"].encode() + b"</html>", "text/html")
            if qq == "fail":  # an error page echoing the encoded query string, long enough to be cut
                return self.send(500, ("x" * 480 + " " + p.query).encode(), "text/plain")
            # Echo the request back the way a careless API might: raw, URL-encoded and in a debug URL.
            return self.send(200, {"response": {"numFound": 1, "docs": [
                {"pid": "p1", "title": "Rain jacket", "url": "https://shop.example.test/p1?colour=red"}]},
                "echo": {"auth_key": q.get("auth_key", [""])[0], "note": "key " + q.get("auth_key", [""])[0],
                         "raw_query": p.query, "said": "you sent " + urllib.parse.quote(q.get("auth_key", [""])[0], safe=""), "debug_url": "https://debug.example.test/x?auth_key=zz-FAKE-zz&q=rain"}})
        if p.path == "/suggest.dxpapi.com/api/v2/suggest/":
            return self.send(200, {"suggestionGroups": [{"querySuggestions": [{"query": "rain jacket", "displayText": "rain jacket"}]}]})
        if p.path == "/api.exponea.com/imports/v1/proj-token-0000":
            if self.headers.get("Authorization") != "Basic " + SECRETS[3]:
                return self.send(401, {"error": "bad credentials " + self.headers.get("Authorization", "")})
            return self.send(200, [IMPORT])
        if p.path == "/api.exponea.com/imports/v1/proj-token-0000/imp_1":
            return self.send(200, [IMPORT])
        return self.send(404, {"error": "not found"})


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.loopback = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        Fake.requests.clear()

    def session(self, messages, env_extra=None, keys=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith("BLOOMREACH_")}
        env.update(KEYS if keys else {})
        env["BLOOMREACH_SAMPLE_LOOPBACK_URL"] = self.loopback
        env["BLOOMREACH_SAMPLE_TEST_MODE"] = "1"
        env.update(env_extra or {})
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SERVER)], input="".join(json.dumps(m) + "\n" for m in messages),
                               capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp, timeout=60)
            self.assertEqual(list(Path(tmp).iterdir()), [], "the server wrote to its working folder")
        for s in SECRETS + ENCODED:
            self.assertNotIn(s, r.stdout + r.stderr, "a secret reached the client or the log")
        return [json.loads(line) for line in r.stdout.splitlines()]

    def call(self, name, arguments=None, **kw):
        out = self.session([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": name, "arguments": arguments or {}}}], **kw)
        res = out[0]["result"]
        return res["isError"], res["content"][0]["text"]

    def test_handshake_and_tools(self):
        out = self.session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/list"}])
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4])  # no reply to the notification
        self.assertEqual(out[0]["result"]["protocolVersion"], "2024-11-05")
        tools = {t["name"]: t for t in out[1]["result"]["tools"]}
        self.assertEqual(set(tools), {"discovery_search", "discovery_autosuggest", "engagement_list_imports",
                                      "engagement_get_import"})
        for t in tools.values():
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertFalse(t["inputSchema"]["additionalProperties"])
            self.assertFalse(any("key" in p or "secret" in p or "token" in p for p in t["inputSchema"]["properties"]))
        self.assertEqual(out[3]["error"]["code"], -32601)

    def test_discovery_search_sends_keys_but_never_returns_them(self):
        err, text = self.call("discovery_search", {"q": "rain jacket", "rows": 5, "fl": "title,url", "fq": ['brand:"Acme"']})
        self.assertFalse(err, text)
        req = Fake.requests[0]
        self.assertEqual(req["query"]["auth_key"], [KEYS["BLOOMREACH_DISCOVERY_AUTH_KEY"]])
        self.assertEqual(req["query"]["account_id"], ["1234"])
        self.assertEqual(req["query"]["domain_key"], ["acme_store"])
        self.assertEqual(req["query"]["request_type"], ["search"])
        self.assertEqual(req["query"]["fl"], ["pid,title,url"])
        self.assertEqual(req["query"]["fq"], ['brand:"Acme"'])
        self.assertEqual(req["query"]["url"], ["https://shop.example.test/"])
        result = json.loads(text)
        self.assertEqual(result["echo"]["auth_key"], "[redacted]")
        self.assertEqual(result["echo"]["note"], "key [redacted]")
        self.assertIn("auth_key=[redacted]", result["echo"]["raw_query"])
        self.assertEqual(result["echo"]["said"], "you sent [redacted]")  # the URL-encoded form, outside a key=value
        self.assertEqual(result["echo"]["debug_url"], "https://debug.example.test/x?auth_key=[redacted]&q=rain")
        # Product URLs keep their query strings; only import sources are stripped.
        self.assertEqual(result["response"]["docs"][0]["url"], "https://shop.example.test/p1?colour=red")

    def test_autosuggest(self):
        err, text = self.call("discovery_autosuggest", {"q": "rai"})
        self.assertFalse(err, text)
        q = Fake.requests[0]["query"]
        self.assertEqual((q["request_type"], q["catalog_views"]), (["suggest"], ["acme_store"]))
        self.assertNotIn("auth_key", q)
        self.assertIn("rain jacket", text)

    def test_engagement_basic_auth_and_redacted_import_sources(self):
        err, text = self.call("engagement_list_imports", {"limit": 5})
        self.assertFalse(err, text)
        self.assertEqual(Fake.requests[0]["query"], {"limit": ["5"], "offset": ["0"]})
        src = json.loads(text)[0]["import_definition"]["source"]
        self.assertEqual(src["auth"], {"username": "[redacted]", "password": "[redacted]"})
        self.assertEqual(src["import_url"], "https://files.example.test/export.csv?[query redacted]")
        for leak in LEAKS:
            self.assertNotIn(leak, text)
        extra = json.loads(text)[0]["import_definition"]["extra"]
        self.assertEqual(extra["headers"][1], {"name": "Accept", "value": "text/csv"})
        self.assertEqual(extra["db_url"], "mysql://[redacted]@db.example.test/x")
        self.assertIn("svc@example.test", extra["service_account"])
        err, text = self.call("engagement_get_import", {"import_id": "imp_1"})
        self.assertFalse(err, text)

    def test_wrong_credentials_error_is_scrubbed(self):
        err, text = self.call("engagement_list_imports", env_extra={"BLOOMREACH_ENGAGEMENT_API_SECRET": "other-FAKE-zz"})
        self.assertTrue(err)
        self.assertIn("HTTP 401", text)
        self.assertNotIn("other-FAKE-zz", text)

    def test_error_bodies_are_scrubbed_before_they_are_cut(self):
        err, text = self.call("discovery_search", {"q": "fail"})
        self.assertTrue(err)
        self.assertIn("HTTP 500", text)
        self.assertNotIn("FAKE", text)

    def test_missing_keys_name_the_variable_not_the_value(self):
        err, text = self.call("discovery_search", {"q": "x"}, keys=False)
        self.assertTrue(err)
        self.assertIn("BLOOMREACH_DISCOVERY_ACCOUNT_ID", text)
        self.assertIn("Don't paste the value into the chat", text)
        self.assertEqual(Fake.requests, [])

    def test_keys_are_not_arguments(self):
        err, text = self.call("discovery_search", {"q": "x", "auth_key": "abc"})
        self.assertTrue(err)
        self.assertIn("Keys are never passed as arguments", text)

    def test_bad_arguments(self):
        for name, args, needle in [("discovery_search", {}, "q is required"),
                                   ("discovery_search", {"q": "x", "rows": 500}, "rows must be between"),
                                   ("discovery_search", {"q": "x", "search_type": "fuzzy"}, "search_type"),
                                   ("engagement_get_import", {"import_id": "../../customers/export"}, "import_id must be"),
                                   ("engagement_list_imports", {"limit": 99}, "limit must be"),
                                   ("nope", {}, "Unknown tool")]:
            err, text = self.call(name, args)
            self.assertTrue(err, name)
            self.assertIn(needle, text)
        self.assertEqual(Fake.requests, [])

    def test_redirects_are_not_followed(self):
        err, text = self.call("discovery_search", {"q": "redirect"})
        self.assertTrue(err)
        self.assertIn("doesn't follow", text)
        self.assertEqual(len(Fake.requests), 1)

    def test_size_cap_and_non_json(self):
        err, text = self.call("discovery_search", {"q": "huge"})
        self.assertTrue(err)
        self.assertIn("over 2 MB", text)
        err, text = self.call("discovery_search", {"q": "notjson"})
        self.assertTrue(err)
        self.assertIn("didn't return JSON", text)

    def test_engagement_base_url_must_be_plain_https(self):
        for base in ("http://api.exponea.com", "https://user:pw@api.exponea.com", "ftp://api.exponea.com"):
            err, text = self.call("engagement_list_imports", env_extra={"BLOOMREACH_ENGAGEMENT_BASE_URL": base})
            self.assertTrue(err, base)
            self.assertIn("plain https://", text)
        for base in ("https://api.exponea.com.evil.example.test", "https://evil.example.test"):
            err, text = self.call("engagement_list_imports", env_extra={"BLOOMREACH_ENGAGEMENT_BASE_URL": base})
            self.assertTrue(err, base)
            self.assertIn("Bloomreach API host", text)
        self.assertEqual(Fake.requests, [])

    def test_loopback_override_needs_test_mode(self):
        err, text = self.call("discovery_autosuggest", {"q": "x"}, env_extra={"BLOOMREACH_SAMPLE_TEST_MODE": ""})
        self.assertTrue(err)
        self.assertIn("for the tests only", text)
        self.assertEqual(Fake.requests, [])

    def test_loopback_override_only_accepts_loopback(self):
        err, text = self.call("discovery_autosuggest", {"q": "x"},
                              env_extra={"BLOOMREACH_SAMPLE_LOOPBACK_URL": "http://evil.example.test:8080"})
        self.assertTrue(err)
        self.assertIn("must be an http://127.0.0.1", text)

    def test_bad_json_rpc(self):
        env = dict(os.environ, BLOOMREACH_SAMPLE_LOOPBACK_URL=self.loopback)
        bad_init = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": "oops"})
        r = subprocess.run([sys.executable, str(SERVER)], input="not json\n[1]\n" + bad_init + "\n", capture_output=True,
                           text=True, encoding="utf-8", env=env, timeout=60)
        codes = [json.loads(l)["error"]["code"] for l in r.stdout.splitlines()]
        self.assertEqual(codes, [-32700, -32600, -32603])
        self.assertEqual(r.stderr, "")


if __name__ == "__main__":
    unittest.main()
