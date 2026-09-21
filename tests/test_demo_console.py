"""Demo console (app/demo.py, served at /demo).

What these tests protect:
  - The scripted scenes do what they say. Every scene in demo.SCENES is
    replayed through the real pipeline and its declared outcome is checked,
    so the demo script cannot drift away from the rules it demonstrates.
  - The privacy line holds in the console too: protected-channel text and
    patterns never appear in /demo/state or in /demo/send results.
  - The console is not reachable unless demo mode is on, because its Reset
    button wipes every table.
  - The console adds no second copy of the rules: it sends through the same
    ingest path as the real webhook and reads thresholds from the same
    function as the desk.
"""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from app import clustering, demo
from app.config import get_config
from app.llm import RuleBasedClient
from app.models import utcnow
from app.server import AppContext, make_handler
from app.storage import make_store

PORT_ON = 8197
PORT_OFF = 8196

PROTECTED_SECRET = "the gateman sold the gate code to the burglars, saw him take the cash"


def _ctx(demo_mode=True):
    return AppContext(config=get_config(), llm=RuleBasedClient(), store=make_store(":memory:"), demo_mode=demo_mode)


def _play(ctx, scene):
    results = []
    for m in scene["messages"]:
        results.append(demo.send_message(ctx, {**m, "community_id": scene["community_id"]}))
    return results


class SceneScriptTests(unittest.TestCase):
    """Every scene, on a clean store, reaches the outcome it declares."""

    def test_every_scene_meets_its_declared_outcome(self):
        config = get_config()
        for scene in demo.SCENES:
            with self.subTest(scene=scene["id"]):
                ctx = _ctx()
                results = _play(ctx, scene)
                community = config.community_by_id(scene["community_id"])
                state = demo.build_state(ctx, community)
                expect = scene["expect"]

                if "pattern_id" in expect:
                    cluster = next((c for c in state["clusters"] if c["pattern_id"] == expect["pattern_id"]), None)
                    self.assertIsNotNone(cluster, f"no {expect['pattern_id']} cluster after scene")
                    if "status" in expect:
                        self.assertEqual(cluster["status"], expect["status"])
                    if "distinct_senders" in expect:
                        self.assertEqual(cluster["distinct_senders"], expect["distinct_senders"])
                    if expect.get("redacted"):
                        self.assertGreaterEqual(cluster["redacted_count"], 1)
                        self.assertTrue(results[-1]["categories_redacted"])
                elif "status" in expect:
                    self.assertEqual(results[-1]["status"], expect["status"])
                    self.assertEqual(state["clusters"], [])
                    self.assertEqual(state["counts"]["refused"], 1)

                if "locale" in expect:
                    for r in results:
                        self.assertEqual(r["locale"], expect["locale"])

                if "protected_waiting" in expect:
                    self.assertEqual(state["protected_inbox"]["waiting"], expect["protected_waiting"])
                    self.assertEqual(state["clusters"], [])

    def test_scene_ids_are_unique_and_reference_real_communities_and_residents(self):
        config = get_config()
        ids = [s["id"] for s in demo.SCENES]
        self.assertEqual(len(ids), len(set(ids)))
        resident_ids = {r["id"] for r in demo.RESIDENTS}
        for scene in demo.SCENES:
            self.assertIsNotNone(config.community_by_id(scene["community_id"]), scene["id"])
            for m in scene["messages"]:
                self.assertIn(m["resident"], resident_ids)
                self.assertIn(m["line"], ("normal", "safe"))

    def test_street_speaks_climbs_through_the_thresholds_one_sender_at_a_time(self):
        ctx = _ctx()
        scene = next(s for s in demo.SCENES if s["id"] == "street-speaks")
        results = _play(ctx, scene)
        self.assertEqual(
            [r["cluster"]["status"] for r in results],
            ["below_threshold", "below_threshold", "below_threshold", "watch", "escalate_ready"],
        )
        self.assertEqual([r["cluster"]["distinct_senders"] for r in results], [1, 2, 3, 4, 5])
        self.assertIsNone(results[0]["previous_status"])
        self.assertEqual(results[4]["previous_status"], "watch")

    def test_one_report_alone_never_reaches_escalate_ready(self):
        ctx = _ctx()
        scene = next(s for s in demo.SCENES if s["id"] == "weapon-fast-lane")
        first = demo.send_message(ctx, {**scene["messages"][0], "community_id": scene["community_id"]})
        self.assertEqual(first["cluster"]["status"], "watch")  # priority, visible at once
        self.assertTrue(first["cluster"]["high_signal"])
        self.assertNotEqual(first["cluster"]["status"], "escalate_ready")

    def test_second_community_uses_a_different_community_without_code_changes(self):
        ctx = _ctx()
        scene = next(s for s in demo.SCENES if s["id"] == "second-community")
        _play(ctx, scene)
        config = get_config()
        self.assertEqual(demo.build_state(ctx, config.community_by_id("oke-ado-phase2"))["clusters"], [])
        self.assertEqual(len(demo.build_state(ctx, config.community_by_id("bodija-close-9"))["clusters"]), 1)


class PresenterRemoteTests(unittest.TestCase):
    """The remote (/demo/remote) is a list of ready-made messages. Its extra
    Q&A messages are checked the same way as the scenes, so a talking point
    like "one phone is one person" cannot quietly stop being true."""

    def test_every_extra_meets_its_declared_outcome(self):
        config = get_config()
        for scene in demo.REMOTE_EXTRAS:
            with self.subTest(scene=scene["id"]):
                ctx = _ctx()
                _play(ctx, scene)
                state = demo.build_state(ctx, config.community_by_id(scene["community_id"]))
                expect = scene["expect"]
                if "pattern_id" in expect:
                    cluster = next((c for c in state["clusters"] if c["pattern_id"] == expect["pattern_id"]), None)
                    self.assertIsNotNone(cluster)
                    self.assertEqual(cluster["status"], expect["status"])
                    self.assertEqual(cluster["distinct_senders"], expect["distinct_senders"])
                if "noise" in expect:
                    self.assertEqual(state["counts"]["noise"], expect["noise"])
                    self.assertEqual(state["clusters"], [])
                if "status" in expect and "pattern_id" not in expect:
                    self.assertEqual(state["counts"]["refused"], 1)
                    self.assertEqual(state["clusters"], [])

    def test_extras_do_not_touch_the_oke_ado_story(self):
        ctx = _ctx()
        for scene in demo.REMOTE_EXTRAS:
            _play(ctx, scene)
        state = demo.build_state(ctx, get_config().community_by_id(demo.OKE_ADO))
        self.assertEqual(state["clusters"], [])

    def test_groups_cover_every_scene_and_extra_with_talking_points(self):
        config = get_config()
        groups = demo.remote_groups()
        self.assertEqual([g["id"] for g in groups], [s["id"] for s in demo.SCENES + demo.REMOTE_EXTRAS])
        resident_ids = {r["id"] for r in demo.RESIDENTS}
        for g in groups:
            with self.subTest(group=g["id"]):
                self.assertNotIn("expect", g)
                self.assertTrue(g["talking_points"])
                self.assertIsNotNone(config.community_by_id(g["community_id"]))
                for m in g["messages"]:
                    self.assertIn(m["resident"], resident_ids)
                    self.assertIn(m["line"], ("normal", "safe"))
        self.assertEqual(len({g["id"] for g in groups}), len(groups))

    def test_crib_numbers_come_from_config(self):
        numbers = demo.presenter_numbers(get_config())
        self.assertEqual(numbers["watch"], {"senders": 3, "days": 3})
        self.assertEqual(numbers["escalate"], {"senders": 5, "days": 3})
        self.assertEqual(numbers["weapon_watch"]["senders"], 1)
        self.assertEqual(numbers["weapon_escalate"], {"senders": 2, "days": 1})
        self.assertEqual(numbers["profiling_pct"], 60)


class SendResultTests(unittest.TestCase):
    def test_redaction_result_keeps_the_behaviour_and_drops_the_identity(self):
        ctx = _ctx()
        scene = next(s for s in demo.SCENES if s["id"] == "identity-stripped")
        result = _play(ctx, scene)[0]
        self.assertNotIn("Hausa", result["redacted_text"])
        self.assertNotIn("stranger", result["redacted_text"])
        self.assertIn("loitering", result["redacted_text"])
        self.assertIn("ethnicity_tribe", result["categories_redacted"])

    def test_refusal_carries_a_human_readable_reason_and_is_not_counted(self):
        ctx = _ctx()
        scene = next(s for s in demo.SCENES if s["id"] == "neighbour-named")
        result = _play(ctx, scene)[0]
        self.assertEqual(result["status"], "rejected_targeting")
        self.assertTrue(result["rejection_reason"])
        self.assertIsNone(result["cluster"])

    def test_noise_is_stored_but_never_forms_a_cluster(self):
        ctx = _ctx()
        result = demo.send_message(ctx, {
            "community_id": "oke-ado-phase2", "resident": 1, "line": "normal", "days_ago": 0,
            "text": "The generator next door was very loud again last night.",
        })
        self.assertEqual(result["pattern_id"], "unclassified")
        state = demo.build_state(ctx, get_config().community_by_id("oke-ado-phase2"))
        self.assertEqual(state["clusters"], [])
        self.assertEqual(state["counts"]["noise"], 1)

    def test_content_fallback_reroutes_a_guard_report_sent_on_the_ordinary_line(self):
        ctx = _ctx()
        result = demo.send_message(ctx, {
            "community_id": "oke-ado-phase2", "resident": 9, "line": "normal", "days_ago": 0,
            "text": "The Amotekun officer on night duty keeps extorting money from drivers at the gate.",
        })
        self.assertEqual(result["channel"], "protected")
        self.assertTrue(result["rerouted"])

    def test_days_ago_backdates_the_report_and_is_clamped(self):
        ctx = _ctx()
        cid = "oke-ado-phase2"
        demo.send_message(ctx, {
            "community_id": cid, "resident": 1, "line": "normal", "days_ago": 4,
            "text": "Strange vehicle parked outside our gate for over an hour last night.",
        })
        demo.send_message(ctx, {
            "community_id": cid, "resident": 2, "line": "normal", "days_ago": 9999,
            "text": "Men unloading at night at the empty house.",
        })
        reports = ctx.store.reports_for_community(cid, channel="normal")
        ages = sorted((utcnow() - r.received_at).total_seconds() / 86400 for r in reports)
        self.assertAlmostEqual(ages[0], 4, delta=0.01)
        self.assertAlmostEqual(ages[1], demo.MAX_DAYS_AGO, delta=0.01)

    def test_validation(self):
        ctx = _ctx()
        ok = {"community_id": "oke-ado-phase2", "resident": 1, "line": "normal", "days_ago": 0, "text": "hello"}
        for change, status in [
            ({"community_id": "nowhere"}, 404),
            ({"resident": 99}, 400),
            ({"resident": "abc"}, 400),
            ({"line": "other"}, 400),
            ({"text": "   "}, 400),
            ({"text": "x" * (demo.MAX_TEXT_LENGTH + 1)}, 400),
            ({"days_ago": "soon"}, 400),
        ]:
            with self.subTest(change=change):
                with self.assertRaises(demo.DemoError) as cm:
                    demo.send_message(ctx, {**ok, **change})
                self.assertEqual(cm.exception.status, status)
        self.assertEqual(ctx.store.all_reports(), [])

    def test_demo_messages_leave_no_phone_number_in_storage(self):
        ctx = _ctx()
        demo.send_message(ctx, {
            "community_id": "oke-ado-phase2", "resident": 3, "line": "normal", "days_ago": 0,
            "text": "Someone was photographing houses on my street this evening.",
        })
        dump = "\n".join(ctx.store._conn.iterdump())
        self.assertNotIn("+23400000", dump)
        self.assertNotIn("23400000", dump)


class SharedRulesTests(unittest.TestCase):
    def test_console_reads_the_same_thresholds_as_the_desk(self):
        config = get_config()
        community = config.community_by_id("oke-ado-phase2")
        by_id = {p.id: p for p in config.patterns}
        watch, escalate = clustering.resolve_thresholds(community, by_id["weapon_sighting"])
        self.assertEqual((watch.min_distinct_senders, escalate.min_distinct_senders), (1, 2))
        watch, escalate = clustering.resolve_thresholds(community, by_id["burglary_casing"])
        self.assertEqual((watch.min_distinct_senders, watch.min_span_days), (3, 3))
        self.assertEqual((escalate.min_distinct_senders, escalate.min_span_days), (5, 3))
        watch, escalate = clustering.resolve_thresholds(community, None)
        self.assertEqual(escalate.min_distinct_senders, 5)

    def test_state_reports_the_thresholds_the_rules_actually_use(self):
        ctx = _ctx()
        scene = next(s for s in demo.SCENES if s["id"] == "weapon-fast-lane")
        _play(ctx, scene)
        state = demo.build_state(ctx, get_config().community_by_id(scene["community_id"]))
        cluster = state["clusters"][0]
        self.assertEqual(cluster["watch"], {"senders": 1, "days": 0})
        self.assertEqual(cluster["escalate"], {"senders": 2, "days": 1})


class DemoModeEnvTests(unittest.TestCase):
    def test_context_is_closed_by_default(self):
        self.assertFalse(AppContext(config=get_config(), llm=RuleBasedClient(), store=make_store(":memory:")).demo_mode)

    def test_env_switch(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(demo.DEMO_ENV, None)
            self.assertTrue(demo.demo_mode_from_env(default=True))
            self.assertFalse(demo.demo_mode_from_env(default=False))
        for off in ("0", "false", "off", "no", ""):
            with mock.patch.dict(os.environ, {demo.DEMO_ENV: off}):
                self.assertFalse(demo.demo_mode_from_env(), off)
        with mock.patch.dict(os.environ, {demo.DEMO_ENV: "1"}):
            self.assertTrue(demo.demo_mode_from_env(default=False))


def _serve(ctx, port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ctx))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _request(port, path, payload=None):
    url = f"http://127.0.0.1:{port}{path}"
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


class DemoServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx(demo_mode=True)
        cls.httpd = _serve(cls.ctx, PORT_ON)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        _request(PORT_ON, "/demo/reset", {})

    def _send(self, **kw):
        body = {"community_id": "oke-ado-phase2", "resident": 1, "line": "normal", "days_ago": 0, "text": "hi"}
        body.update(kw)
        return _request(PORT_ON, "/demo/send", body)

    def test_page_renders_with_every_scene_and_a_composer(self):
        status, html = _request(PORT_ON, "/demo")
        self.assertEqual(status, 200)
        for scene in demo.SCENES:  # the boot JSON escapes non-ASCII (Yorùbá) as \uXXXX
            self.assertTrue(scene["title"] in html or json.dumps(scene["title"])[1:-1] in html, scene["title"])
        self.assertIn('id="composer-text"', html)

    def test_remote_page_renders_every_group_and_the_crib_numbers(self):
        status, html = _request(PORT_ON, "/demo/remote")
        self.assertEqual(status, 200)
        for group in demo.remote_groups():  # titles are drawn by the page script from the boot JSON
            self.assertIn('"id": "%s"' % group["id"], html)
        self.assertIn("Watch: 3 people across 3 days", html)
        self.assertIn("over 60% redacted", html)
        self.assertNotIn('"expect"', html)

    def test_console_links_to_the_remote(self):
        _, html = _request(PORT_ON, "/demo")
        self.assertIn("/demo/remote", html)

    def test_protected_text_never_appears_in_state_or_send_result(self):
        status, body = self._send(line="safe", resident=8, text=PROTECTED_SECRET)
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["channel"], "protected")
        for forbidden in ("gate code", "burglars", "redacted_text", "pattern_id", "pattern_name"):
            self.assertNotIn(forbidden, body)

        for cid in ("oke-ado-phase2", "bodija-close-9"):
            status, state_body = _request(PORT_ON, f"/demo/state?community={cid}")
            self.assertEqual(status, 200)
            self.assertNotIn("gate code", state_body)
            self.assertNotIn("burglars", state_body)
        state = json.loads(_request(PORT_ON, "/demo/state?community=oke-ado-phase2")[1])
        self.assertEqual(state["protected_inbox"], {"waiting": 1, "escalated": 0})
        self.assertEqual(state["clusters"], [])
        self.assertEqual(state["feed"], [])

    def test_rerouted_message_text_is_not_returned_either(self):
        status, body = self._send(resident=9, text="The Amotekun officer keeps extorting money from drivers at the gate.")
        result = json.loads(body)
        self.assertTrue(result["rerouted"])
        self.assertNotIn("extorting", body)
        self.assertNotIn("redacted_text", body)

    def test_state_has_no_clock_times_and_no_sender_identity(self):
        self._send(resident=4, text="Someone was photographing houses on my street this evening.")
        _, state_body = _request(PORT_ON, "/demo/state?community=oke-ado-phase2")
        import re
        self.assertIsNone(re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\b", state_body))
        self.assertNotIn("sender_hash", state_body)
        self.assertNotIn("23400000", state_body)

    def test_reset_wipes_everything_and_the_scene_can_be_replayed(self):
        scene = next(s for s in demo.SCENES if s["id"] == "street-speaks")
        for m in scene["messages"]:
            self.assertEqual(self._send(**m)[0], 200)
        self.assertEqual(json.loads(_request(PORT_ON, "/demo/state?community=oke-ado-phase2")[1])["counts"]["total"], 5)

        self.assertEqual(_request(PORT_ON, "/demo/reset", {})[0], 200)
        state = json.loads(_request(PORT_ON, "/demo/state?community=oke-ado-phase2")[1])
        self.assertEqual(state["counts"]["total"], 0)
        self.assertEqual(state["clusters"], [])
        self.assertEqual(self.ctx.store.all_reports(), [])
        self.assertEqual(self.ctx.store.pending_inbound(), [])

        for m in scene["messages"]:
            self._send(**m)
        state = json.loads(_request(PORT_ON, "/demo/state?community=oke-ado-phase2")[1])
        self.assertEqual(state["clusters"][0]["status"], "escalate_ready")

    def test_escalating_from_the_desk_shows_on_the_board(self):
        scene = next(s for s in demo.SCENES if s["id"] == "street-speaks")
        for m in scene["messages"]:
            self._send(**m)
        status, _ = _request(PORT_ON, "/desk/escalate", {
            "community_id": "oke-ado-phase2", "pattern_id": "burglary_casing", "decided_by": "Committee chair",
        })
        self.assertIn(status, (200, 303))
        state = json.loads(_request(PORT_ON, "/demo/state?community=oke-ado-phase2")[1])
        self.assertEqual(state["clusters"][0]["status"], "escalated")
        self.assertEqual(state["escalations"][0]["decided_by"], "Committee chair")

    def test_bad_requests_get_json_errors(self):
        status, body = self._send(text="")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))
        self.assertEqual(self._send(community_id="nowhere")[0], 404)
        self.assertEqual(_request(PORT_ON, "/demo/state?community=nowhere")[0], 404)

    def test_existing_webhook_response_shape_is_unchanged(self):
        status, body = _request(PORT_ON, "/simulate/inbound", {
            "id": "shape-1", "to": "40404*REPORT-OKEADO2", "from": "+2340000009999",
            "text": "Someone was photographing houses on my street.",
        })
        self.assertEqual(status, 200)
        self.assertEqual(
            sorted(json.loads(body).keys()),
            ["accepted", "channel", "pattern_id", "processed", "report_id", "status"],
        )


class DemoModeOffTests(unittest.TestCase):
    """The console's reset wipes every table, so with demo mode off none of
    its routes may exist, and nothing else about the server changes."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx(demo_mode=False)
        cls.httpd = _serve(cls.ctx, PORT_OFF)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_every_demo_route_is_404_and_data_is_untouched(self):
        _request(PORT_OFF, "/simulate/inbound", {
            "id": "keep-1", "to": "40404*REPORT-OKEADO2", "from": "+2340000000001",
            "text": "Someone was photographing houses on my street.",
        })
        self.assertEqual(_request(PORT_OFF, "/demo")[0], 404)
        self.assertEqual(_request(PORT_OFF, "/demo/state")[0], 404)
        self.assertEqual(_request(PORT_OFF, "/demo/send", {"text": "x"})[0], 404)
        self.assertEqual(_request(PORT_OFF, "/demo/reset", {})[0], 404)
        self.assertEqual(_request(PORT_OFF, "/demo/remote")[0], 404)
        self.assertEqual(len(self.ctx.store.all_reports()), 1)

    def test_landing_page_does_not_advertise_the_console(self):
        status, html = _request(PORT_OFF, "/")
        self.assertEqual(status, 200)
        self.assertNotIn("/demo", html)


if __name__ == "__main__":
    unittest.main()
