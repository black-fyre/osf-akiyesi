"""Yoruba support: the pipeline reads a Yoruba SMS as well as an English one.

What these tests protect:
  - A message's language is detected per message (no menu on a basic
    phone), and an explicit hint wins.
  - Tone marks do not matter: "Àjèjì" and "Ajeji" are the same word to
    every word list.
  - The two safety layers (redaction and the accusation guard) check every
    language on every message, whatever was detected. Written after a test
    caught the first version letting "Ajeji kan was loitering..." keep
    "Ajeji" because the message was detected as English, and letting
    "Baba Bello je ole, e lu u." through because it was too short to be
    detected as Yoruba. Both are pinned below.
  - English behaviour is unchanged (the rest of the suite covers this; one
    regression check here too).
"""
import unittest

from app.config import get_config
from app.llm import RuleBasedClient
from app.locale_detect import detect_locale
from app.pipeline import STATUS_REJECTED_TARGETING, STATUS_STORED, process_inbound
from app.storage import make_store
from app.textnorm import fold, replace_phrase

NORMAL = "40404*REPORT-OKEADO2"


class FoldTests(unittest.TestCase):
    def test_tone_marks_and_case_fold_away(self):
        self.assertEqual(fold("Àjèjì"), "ajeji")
        self.assertEqual(fold("Háúsá"), "hausa")
        self.assertEqual(fold("wọ́n ń wo ilé"), "won n wo ile")

    def test_replacement_keeps_the_rest_of_the_original_text(self):
        out, hit = replace_phrase("Àjèjì kan ń rìn kiri ní òru.", "ajeji", "[person]")
        self.assertTrue(hit)
        self.assertEqual(out, "[person] kan ń rìn kiri ní òru.")

    def test_whole_words_only(self):
        # "Tapa" (a yo ethnic term) must not match inside another word.
        out, hit = replace_phrase("He was tapping the gate.", "Tapa", "[REDACTED]")
        self.assertFalse(hit)
        self.assertEqual(out, "He was tapping the gate.")


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()

    def detect(self, text, hint=None):
        return detect_locale(text, "en-NG", self.config, hint=hint)

    def test_yoruba_without_tone_marks(self):
        self.assertEqual(self.detect("Mo ri okunrin meji ti won n gbe apo sinu ile ni oru."), "yo")

    def test_yoruba_with_tone_marks(self):
        self.assertEqual(self.detect("Ọkùnrin kan dúró síbẹ̀."), "yo")

    def test_english_stays_english(self):
        for text in (
            "Two men were unloading sacks at the empty house around midnight.",
            "Someone was photographing houses on my street this evening.",
            "The Amotekun officer on night duty keeps extorting money from drivers at the gate.",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "en-NG")

    def test_hint_wins(self):
        self.assertEqual(self.detect("Someone was checking gates.", hint="yo"), "yo")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.store = make_store(":memory:")
        self.n = 0

    def send(self, text, to=NORMAL):
        self.n += 1
        return process_inbound(
            {"id": f"yo-{self.n}", "to": to, "from": f"+23400009{self.n:04d}", "text": text},
            self.config, self.llm, self.store,
        )

    def test_stranger_word_is_stripped_and_the_behaviour_is_counted(self):
        r = self.send("Àjèjì kan ń rìn kiri ní òru, wọ́n ń wo ilé wa.")
        self.assertEqual(r.locale_detected, "yo")
        self.assertEqual(r.status, STATUS_STORED)
        self.assertEqual(r.pattern_id, "burglary_casing")
        self.assertIn("stranger_or_foreigner_markers", r.categories_redacted)
        self.assertNotIn("jèjì", r.redacted_text)
        self.assertIn("wo ilé wa", r.redacted_text)

    def test_ethnic_group_is_stripped_in_a_yoruba_sentence(self):
        r = self.send("Okunrin Hausa kan n ya aworan ile ni adugbo wa lana.")
        self.assertIn("ethnicity_tribe", r.categories_redacted)
        self.assertNotIn("Hausa", r.redacted_text)
        self.assertEqual(r.pattern_id, "burglary_casing")

    def test_code_switched_message_detected_as_english_still_loses_the_yoruba_identity_word(self):
        r = self.send("Ajeji kan was loitering by the gate at night.")
        self.assertEqual(r.locale_detected, "en-NG")
        self.assertIn("stranger_or_foreigner_markers", r.categories_redacted)
        self.assertNotIn("Ajeji", r.redacted_text)

    def test_short_yoruba_accusation_is_refused(self):
        r = self.send("Baba Bello je ole, e lu u.")
        self.assertEqual(r.status, STATUS_REJECTED_TARGETING)
        self.assertIn("Bello", r.rejection_reason)

    def test_inverted_accusation_is_refused(self):
        r = self.send("Ole ni Tunde, mo ri i.")
        self.assertEqual(r.status, STATUS_REJECTED_TARGETING)

    def test_ni_meaning_at_is_not_an_accusation(self):
        # "awon ole ni Adeoye street": robbers AT Adeoye street.
        r = self.send("Mo ri awon ole ni Adeoye street pelu ibon ni oru.")
        self.assertEqual(r.status, STATUS_STORED)
        self.assertEqual(r.pattern_id, "weapon_sighting")

    def test_report_about_the_gateman_is_rerouted_to_the_protected_channel(self):
        r = self.send("Maigadi ti n gba owo tipatipa lowo awon awako ni geeti.")
        self.assertEqual(r.channel, "protected")

    def test_yoruba_explosives_pattern(self):
        r = self.send("Oorun kemika n jade lati ile ise yen ni oru, won n ko dromu wole.")
        self.assertEqual(r.pattern_id, "explosives_storage")

    def test_yoruba_noise_is_not_counted(self):
        r = self.send("Ewure wa sonu ni adugbo wa lana, e jowo e pe mi.")
        self.assertEqual(r.locale_detected, "yo")
        self.assertEqual(r.pattern_id, "unclassified")

    def test_english_is_unchanged(self):
        r = self.send("A Hausa stranger was loitering by the gate at night, checking the locks on parked cars.")
        self.assertEqual(r.locale_detected, "en-NG")
        self.assertEqual(r.redacted_text, "A [REDACTED] [person] was loitering by the gate at night, checking the locks on parked cars.")
        self.assertEqual(self.send("Mr Bello is a thief, someone should deal with him.").status, STATUS_REJECTED_TARGETING)

    def test_unsupported_locale_is_still_held_for_review(self):
        r = process_inbound(
            {"id": "fr-1", "to": NORMAL, "from": "+2340000777", "text": "Des hommes la nuit.", "locale": "fr"},
            self.config, self.llm, self.store,
        )
        self.assertEqual(r.status, "needs_review_locale")


if __name__ == "__main__":
    unittest.main()
