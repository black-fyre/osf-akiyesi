"""Claude as the default reader, with the rule-based lists as floor and fallback.

What these tests protect:
  - get_llm_client() picks Claude by default, stays loud when Claude was
    asked for explicitly but cannot be set up, and falls back with a
    warning only when nobody asked.
  - GuardedClaudeClient: the config word lists still run over Claude's
    redaction (the model can widen protection, never narrow it); a message
    either reader thinks is about the guards goes to the protected channel;
    any failed call falls back to the rule-based client, so an API error in
    the middle of a demo never loses a message.
  - Fallback and floor notes reach the demo console, and never carry
    message content.
  - .env is loaded without overriding exported variables or setting empty
    placeholders (an empty AKIYESI_CONFIG_DIR would break config loading).
No network: Claude is a fake throughout.
"""
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import demo, llm
from app.config import get_config
from app.envfile import load_env_file
from app.llm import GuardedClaudeClient, RedactionResult, RuleBasedClient
from app.server import AppContext
from app.storage import make_store

TERMS = {"ethnicity_tribe": ["Hausa"], "stranger_or_foreigner_markers": ["ajeji", "stranger"]}


class FakeClaude:
    model_name = "claude-fake"

    def __init__(self, redact_text=None, channel="normal", fail=()):
        self.redact_text = redact_text
        self.channel = channel
        self.fail = set(fail)

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError("Anthropic API call failed: timed out")

    def redact(self, text, terms):
        self._maybe_fail("redact")
        return RedactionResult(redacted_text=self.redact_text if self.redact_text is not None else text, categories_redacted=[])

    def classify_channel(self, text, terms):
        self._maybe_fail("classify")
        return self.channel

    def score_patterns(self, text, pattern_keywords):
        self._maybe_fail("score")
        return {pid: (2 if pid == "burglary_casing" else 0) for pid in pattern_keywords}


class GuardedClientTests(unittest.TestCase):
    def test_word_lists_remove_what_claude_left_in(self):
        client = GuardedClaudeClient(FakeClaude(), RuleBasedClient())
        result = client.redact("Ajeji kan was loitering by the gate.", TERMS)
        self.assertNotIn("Ajeji", result.redacted_text)
        self.assertIn("stranger_or_foreigner_markers", result.categories_redacted)
        events = client.drain_events()
        self.assertEqual(len(events), 1)
        self.assertIn("also removed", events[0])
        self.assertNotIn("Ajeji", events[0])  # notes never carry message content
        self.assertEqual(client.drain_events(), [])

    def test_claude_redaction_kept_when_lists_find_nothing_more(self):
        client = GuardedClaudeClient(FakeClaude(redact_text="A [REDACTED] man was checking gates."), RuleBasedClient())
        result = client.redact("A Hausa man was checking gates.", TERMS)
        self.assertEqual(result.redacted_text, "A [REDACTED] man was checking gates.")
        self.assertEqual(client.drain_events(), [])

    def test_every_step_falls_back_when_claude_fails(self):
        client = GuardedClaudeClient(FakeClaude(fail={"redact", "classify", "score"}), RuleBasedClient())
        r = client.redact("A Hausa stranger was loitering.", TERMS)
        self.assertEqual(r.categories_redacted, ["ethnicity_tribe", "stranger_or_foreigner_markers"])
        self.assertEqual(client.classify_channel("the gateman took money", ["gateman"]), "protected")
        self.assertEqual(client.score_patterns("loitering", {"burglary_casing": ["loitering"]}), {"burglary_casing": 1})
        events = client.drain_events()
        self.assertEqual(len(events), 3)
        self.assertTrue(all("did not answer" in e for e in events))

    def test_either_reader_can_send_a_report_to_the_protected_channel(self):
        rules = RuleBasedClient()
        self.assertEqual(GuardedClaudeClient(FakeClaude(channel="normal"), rules).classify_channel("the gateman took money", ["gateman"]), "protected")
        self.assertEqual(GuardedClaudeClient(FakeClaude(channel="protected"), rules).classify_channel("an ordinary report", ["gateman"]), "protected")
        self.assertEqual(GuardedClaudeClient(FakeClaude(channel="normal"), rules).classify_channel("an ordinary report", ["gateman"]), "normal")


class ChoiceOfClientTests(unittest.TestCase):
    def test_claude_is_the_default(self):
        with mock.patch.dict(os.environ, {"AKIYESI_ANTHROPIC_API_KEY": "k"}, clear=False):
            os.environ.pop("AKIYESI_LLM_BACKEND", None)
            with mock.patch.object(llm, "AnthropicClient", lambda api_key, model_name: FakeClaude()):
                self.assertIsInstance(llm.get_llm_client(), GuardedClaudeClient)

    def test_unset_backend_without_claude_warns_and_runs_rules(self):
        def broken(api_key, model_name):
            raise RuntimeError("AnthropicClient requires AKIYESI_ANTHROPIC_API_KEY.")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AKIYESI_LLM_BACKEND", None)
            with mock.patch.object(llm, "AnthropicClient", broken), mock.patch("sys.stderr", new=io.StringIO()) as err:
                self.assertIsInstance(llm.get_llm_client(), RuleBasedClient)
            self.assertIn("rule-based", err.getvalue())

    def test_explicit_claude_that_cannot_start_is_loud(self):
        def broken(api_key, model_name):
            raise RuntimeError("no key")
        with mock.patch.dict(os.environ, {"AKIYESI_LLM_BACKEND": "anthropic_claude"}):
            with mock.patch.object(llm, "AnthropicClient", broken):
                with self.assertRaises(RuntimeError):
                    llm.get_llm_client()

    def test_explicit_rule_based_still_works(self):
        with mock.patch.dict(os.environ, {"AKIYESI_LLM_BACKEND": "rule_based"}):
            self.assertIsInstance(llm.get_llm_client(), RuleBasedClient)


class DemoReaderTests(unittest.TestCase):
    def _ctx(self, claude):
        return AppContext(config=get_config(), llm=GuardedClaudeClient(claude, RuleBasedClient()), store=make_store(":memory:"), demo_mode=True)

    def test_a_message_still_lands_when_claude_is_down(self):
        ctx = self._ctx(FakeClaude(fail={"redact", "classify", "score"}))
        r = demo.send_message(ctx, {"community_id": "oke-ado-phase2", "resident": 1, "line": "normal", "days_ago": 0,
                                    "text": "A Hausa stranger was loitering by the gate at night."})
        self.assertTrue(r["processed"])
        self.assertEqual(r["reader"]["name"], "Claude")
        self.assertEqual(len(r["reader"]["events"]), 3)
        self.assertEqual(r["pattern_id"], "burglary_casing")
        self.assertNotIn("Hausa", r["redacted_text"])

    def test_protected_result_carries_no_content_in_reader_notes(self):
        ctx = self._ctx(FakeClaude())
        r = demo.send_message(ctx, {"community_id": "oke-ado-phase2", "resident": 8, "line": "safe", "days_ago": 0,
                                    "text": "The gateman sold the gate code to the burglars."})
        self.assertEqual(r["channel"], "protected")
        blob = repr(r)
        for forbidden in ("gate code", "burglars", "redacted_text"):
            self.assertNotIn(forbidden, blob)


class EnvFileTests(unittest.TestCase):
    def test_loads_without_overriding_or_setting_empties(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_text(
                "# comment\n"
                "AKIYESI_TEST_A=one\n"
                "export AKIYESI_TEST_B=\"two\"\n"
                "AKIYESI_TEST_EMPTY=\n"
                "AKIYESI_TEST_KEEP=from-file\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"AKIYESI_TEST_KEEP": "exported"}):
                loaded = load_env_file(path)
                self.assertEqual(os.environ["AKIYESI_TEST_A"], "one")
                self.assertEqual(os.environ["AKIYESI_TEST_B"], "two")
                self.assertNotIn("AKIYESI_TEST_EMPTY", os.environ)
                self.assertEqual(os.environ["AKIYESI_TEST_KEEP"], "exported")
                self.assertEqual(sorted(loaded), ["AKIYESI_TEST_A", "AKIYESI_TEST_B"])
            for k in ("AKIYESI_TEST_A", "AKIYESI_TEST_B"):
                os.environ.pop(k, None)

    def test_missing_file_is_fine(self):
        self.assertEqual(load_env_file(Path("/nonexistent/.env")), [])


if __name__ == "__main__":
    unittest.main()
