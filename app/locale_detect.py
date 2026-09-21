"""Per-message language detection (scalability seam #2: language is config).

A basic phone has no language menu, and a community's default language is
not everyone's. So each message's locale is decided per message:

  1. an explicit hint on the payload (a provider or keyword can set one),
  2. otherwise the markers in config/locales.yaml: a letter only one
     language uses (Yoruba's under-dot letters ẹ ọ ṣ), or enough distinct
     common words of that language,
  3. otherwise the community's default locale.

Detection only picks which word lists to use. It never drops a message:
the pipeline still stores anything it cannot read, and matches every
message against both the detected locale's lists and the community's own
(people code-switch mid-sentence), so a wrong guess costs precision, not
safety.

The raw text is read here and nowhere is it kept; only the locale code
comes back.
"""
from __future__ import annotations

import re
from typing import Optional

from app.config import AppConfig
from app.textnorm import fold

_WORD = re.compile(r"[a-z]+")


def detect_locale(text: str, community_locale: str, config: AppConfig, hint: Optional[str] = None) -> str:
    if hint:
        return hint
    words = set(_WORD.findall(fold(text)))
    lowered = text.lower()
    for locale, markers in config.locale_markers.items():
        if locale == community_locale:
            continue
        if any(ch in lowered for ch in markers.letters):
            return locale
        hits = words.intersection(markers.words)
        if len(hits) >= markers.min_distinct_words:
            return locale
    return community_locale
