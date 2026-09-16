"""CLAUDE.md required tests:
- A protected-channel report is never visible to a desk user.
- Desk view exposes no timestamp finer than daily.

Integration-style: runs the real HTTP server (app/server.py) against a
free local port and hits it with plain urllib, the same way a browser
would, rather than calling internal functions directly -- this is the
strongest form of the "never visible" guarantee, since a template typo
that leaked protected content would still be caught here.
"""
import json
import re
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from app.config import get_config
from app.llm import RuleBasedClient
from app.storage import make_store
from app.server import AppContext, make_handler

PORT = 8199
BASE = f"http://127.0.0.1:{PORT}"

# Matches an HH:MM (or HH:MM:SS) clock time -- the thing design rule #4
# says the desk view must never expose, since in a neighbourhood of a few
# hundred people, timing deanonymises a reporter.
_TIME_OF_DAY_RE = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b")

PROTECTED_SECRET_TEXT = "gateman colluding with the burglars, saw him unlock the back gate himself"


class DeskServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctx = AppContext(config=get_config(), llm=RuleBasedClient(), store=make_store(":memory:"))
        cls.ctx = ctx
        handler = make_handler(ctx)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        # Seed: five normal-channel reports (enough to escalate) plus one
        # protected-channel report with a distinctive secret string that
        # must never surface on any /desk* page.
        for i in range(5):
            cls._post("/webhook/sms", {
                "id": f"desk-test-normal-{i}",
                "to": "40404*REPORT-OKEADO2",
                "from": f"+234803{i:07d}",
                "text": f"Someone was checking gates along the street, report {i}.",
                "date": f"2026-02-0{i+1}T21:00:00+00:00",
            })
        cls._post("/webhook/sms", {
            "id": "desk-test-protected-1",
            "to": "40404*SAFE-OKEADO2",
            "from": "+2348039999999",
            "text": PROTECTED_SECRET_TEXT,
            "date": "2026-02-10T13:45:00+00:00",
        })

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    @classmethod
    def _post(cls, path, payload):
        req = urllib.request.Request(
            BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())

    @classmethod
    def _get(cls, path):
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, resp.read().decode()

    @classmethod
    def _post_form_expect_redirect(cls, path, payload):
        # /desk/escalate responds 303 with no body; urllib auto-follows
        # redirects, so just draining the response (rather than treating it
        # as JSON) is enough to confirm the escalate call itself succeeded.
        req = urllib.request.Request(
            BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            resp.read()
            return resp.status

    def test_protected_report_never_appears_on_desk_list(self):
        status, body = self._get("/desk?community=oke-ado-phase2")
        self.assertEqual(status, 200)
        self.assertNotIn(PROTECTED_SECRET_TEXT, body)
        self.assertNotIn("gateman", body.lower())

    def test_protected_report_never_appears_on_desk_cluster_detail(self):
        status, body = self._get("/desk/cluster?community=oke-ado-phase2&pattern=burglary_casing")
        self.assertEqual(status, 200)
        self.assertNotIn(PROTECTED_SECRET_TEXT, body)

    def test_protected_report_never_appears_on_desk_audit_log(self):
        # Escalate the normal cluster, then check the desk audit view.
        self._post_form_expect_redirect(
            "/desk/escalate", {"community_id": "oke-ado-phase2", "pattern_id": "burglary_casing", "decided_by": "tester"}
        )
        status, body = self._get("/desk/audit?community=oke-ado-phase2")
        self.assertEqual(status, 200)
        self.assertNotIn(PROTECTED_SECRET_TEXT, body)

    def test_protected_report_only_appears_in_its_own_outbox(self):
        status, body = self._get("/protected-outbox?community=oke-ado-phase2")
        self.assertEqual(status, 200)
        self.assertIn("gateman", body.lower())

    def test_desk_list_exposes_no_finer_than_daily_timestamp(self):
        status, body = self._get("/desk?community=oke-ado-phase2")
        self.assertEqual(status, 200)
        self.assertIsNone(_TIME_OF_DAY_RE.search(body), "desk list leaked a clock time")

    def test_desk_cluster_detail_exposes_no_finer_than_daily_timestamp(self):
        status, body = self._get("/desk/cluster?community=oke-ado-phase2&pattern=burglary_casing")
        self.assertEqual(status, 200)
        self.assertIsNone(_TIME_OF_DAY_RE.search(body), "referral brief leaked a clock time")


if __name__ == "__main__":
    unittest.main()
