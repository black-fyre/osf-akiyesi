"""Quick send page (/demo/quick): a plain form over demo.send_message.

What these tests protect:
  - A message and a whole scene go through the real pipeline and show up in
    the page's log, with the redacted text rather than the original.
  - Protected-line text never appears on the page.
  - Every action redirects back, so a refresh cannot resend a message.
  - The page is not reachable unless demo mode is on (its Reset wipes data).
"""
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from app import demo
from app.config import get_config
from app.llm import RuleBasedClient
from app.server import AppContext, make_handler
from app.storage import make_store

PORT = 8195
PORT_OFF = 8194
SECRET = "the gateman sold the gate code to the burglars, saw him take the cash"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _serve(port, demo_mode):
    ctx = AppContext(config=get_config(), llm=RuleBasedClient(), store=make_store(":memory:"), demo_mode=demo_mode)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ctx))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return ctx, server


class QuickPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx, cls.server = _serve(PORT, True)
        cls.base = f"http://127.0.0.1:{PORT}"
        cls.opener = urllib.request.build_opener(_NoRedirect)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        demo.reset(self.ctx)
        self.ctx.quick_log.clear()

    def _post(self, action, **fields):
        data = urllib.parse.urlencode(fields).encode()
        try:
            self.opener.open(f"{self.base}/demo/quick/{action}", data=data)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Location")
        self.fail("expected a redirect")

    def _page(self, community=demo.OKE_ADO):
        with urllib.request.urlopen(f"{self.base}/demo/quick?community={community}") as resp:
            return resp.read().decode()

    def test_send_redirects_and_logs_redacted_text(self):
        status, location = self._post(
            "send", community_id=demo.OKE_ADO, resident=6, line="normal", days_ago=0,
            text="A Hausa stranger was loitering by the gate at night, checking the locks on parked cars.",
        )
        self.assertEqual(status, 303)
        self.assertEqual(location, f"/demo/quick?community={demo.OKE_ADO}")
        page = self._page()
        self.assertIn("loitering", page)
        self.assertNotIn("Hausa", page.split("<table>")[1])

    def test_scene_plays_every_message_and_switches_community(self):
        scene = next(s for s in demo.SCENES if s["id"] == "second-community")
        _, location = self._post("scene", scene=scene["id"])
        self.assertEqual(location, f"/demo/quick?community={demo.BODIJA}")
        self.assertEqual(len(self.ctx.quick_log), len(scene["messages"]))
        self.assertIn("escalate ready", self._page(demo.BODIJA))

    def test_protected_text_never_on_page(self):
        self._post("send", community_id=demo.OKE_ADO, resident=8, line="safe", days_ago=0, text=SECRET)
        page = self._page()
        self.assertNotIn("gate code", page)
        self.assertIn("protected inbox", page)

    def test_bad_input_shows_error_not_crash(self):
        data = urllib.parse.urlencode({"community_id": demo.OKE_ADO, "resident": 99, "text": "x"}).encode()
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.opener.open(f"{self.base}/demo/quick/send", data=data)
        self.assertEqual(err.exception.code, 400)
        self.assertIn("unknown resident", err.exception.read().decode())

    def test_reset_clears_log(self):
        self._post("scene", scene="neighbour-named")
        self._post("reset", community_id=demo.OKE_ADO)
        self.assertEqual(self.ctx.quick_log, [])
        self.assertIn("Nothing sent yet", self._page())


class QuickPageOffTests(unittest.TestCase):
    def test_404_when_demo_mode_off(self):
        _, server = _serve(PORT_OFF, False)
        try:
            for method, path in (("GET", "/demo/quick"), ("POST", "/demo/quick/reset")):
                req = urllib.request.Request(f"http://127.0.0.1:{PORT_OFF}{path}", data=b"" if method == "POST" else None, method=method)
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(req)
                self.assertEqual(err.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
