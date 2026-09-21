"""Tone-mark-insensitive text matching.

Yoruba is written with tone marks and under-dots (ẹ, ọ, ṣ, à, á), but on a
basic phone most people type it without them, and the same person may do
both in one message. A word list that only matched one spelling would miss
the other, and for the redaction layer a miss means identity content
reaching the pattern store. So every word-list match in the rule-based
pipeline goes through fold(): decompose, drop the combining marks, lower
case. "Háúsá", "HAUSA" and "hausa" all fold to "hausa".

English text is unchanged by folding apart from case, so the existing
en-NG behaviour is identical.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple


def _fold_char(ch: str) -> str:
    decomposed = unicodedata.normalize("NFD", ch)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fold(text: str, lower: bool = True) -> str:
    out = "".join(_fold_char(c) for c in text)
    return out.lower() if lower else out


def folded_with_map(text: str) -> Tuple[str, List[int]]:
    """Folded (lower-cased) text plus, for each folded character, the index
    of the original character it came from. Used to find a match in the
    folded text and replace the matching span of the *original* text."""
    chars: List[str] = []
    index: List[int] = []
    for i, ch in enumerate(text):
        for f in _fold_char(ch).lower():
            chars.append(f)
            index.append(i)
    return "".join(chars), index


def phrase_regex(phrase: str) -> "re.Pattern[str]":
    """Whole-phrase pattern over folded text. Internal whitespace matches
    any run of spaces, so "ki i se omo ibi" survives a double space."""
    parts = [re.escape(p) for p in fold(phrase).split()]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b")


def contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase_regex(phrase).search(fold(text)))


def replace_phrase(text: str, phrase: str, placeholder: str) -> Tuple[str, bool]:
    """Replace every whole-phrase, tone-mark-insensitive occurrence of
    `phrase` in `text` with `placeholder`, keeping the rest of the original
    text (including its tone marks) exactly as written."""
    pattern = phrase_regex(phrase)
    folded, index = folded_with_map(text)
    spans = []
    for m in pattern.finditer(folded):
        if m.end() == m.start():
            continue
        start = index[m.start()]
        end = index[m.end() - 1] + 1
        # A decomposed mark typed after the last letter belongs to the match.
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        spans.append((start, end))
    if not spans:
        return text, False
    out, last = [], 0
    for start, end in spans:
        out.append(text[last:start])
        out.append(placeholder)
        last = end
    out.append(text[last:])
    return "".join(out), True
