"""Config loading.

Every value a new community, language or pattern needs is a row in one of
the YAML files under config/, never a code change (see the "Scalability
seams" section of CLAUDE.md). This module's only job is to turn those files
into typed, validated Python objects, and to fail loudly -- not with a
default -- when a config file is missing a value a community needs.

No third-party dependency (pydantic, etc.) is used here: the sandbox this
first iteration was built in has no package-registry access (see
docs/ai-usage.md), so app/ is deliberately standard-library only. The shape
mirrors what a pydantic BaseSettings model would look like, so swapping one
in later is a small, contained change.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = Path(os.environ.get("AKIYESI_CONFIG_DIR", REPO_ROOT / "config"))


class ConfigError(Exception):
    """Raised when config/*.yaml is missing or malformed."""


@dataclass(frozen=True)
class Recipient:
    name: str
    contact: str


@dataclass(frozen=True)
class SpanThreshold:
    min_distinct_senders: int
    min_span_days: int


@dataclass(frozen=True)
class NormalChannelThresholds:
    watch: SpanThreshold
    escalate: SpanThreshold


@dataclass(frozen=True)
class ProtectedChannelThreshold:
    min_distinct_senders: int
    min_span_days: int


@dataclass(frozen=True)
class Thresholds:
    normal_channel: NormalChannelThresholds
    protected_channel: ProtectedChannelThreshold
    profiling_guard_max_redacted_fraction: float


@dataclass(frozen=True)
class Community:
    id: str
    name: str
    locale: str
    normal_inbound: str
    protected_inbound: str
    protected_recipients: List[Recipient]
    desk_recipients: List[Recipient]
    thresholds: Thresholds  # already merged with defaults


@dataclass(frozen=True)
class PatternDefinition:
    id: str
    name: str
    locale_keywords: Dict[str, List[str]]
    # A pattern can carry its own corroboration bar instead of inheriting
    # the community's thresholds.yaml default -- app/clustering.py resolves
    # these first, falling back to community.thresholds.normal_channel when
    # a pattern doesn't set them. high_signal is a separate, purely
    # descriptive flag (drives the desk UI's priority badge); it does not
    # by itself change any threshold -- see config/patterns.yaml's
    # file-level comment for why these are kept as two independent knobs.
    high_signal: bool = False
    watch_override: Optional[SpanThreshold] = None
    escalate_override: Optional[SpanThreshold] = None

    def keywords_for(self, locale) -> List[str]:
        locales = [locale] if isinstance(locale, str) else list(locale)
        merged: List[str] = []
        for loc in locales:
            for kw in self.locale_keywords.get(loc, []) or []:
                if kw not in merged:
                    merged.append(kw)
        return merged


@dataclass(frozen=True)
class RedactionTerms:
    # category -> locale -> list of phrases
    categories: Dict[str, Dict[str, List[str]]]

    def terms_for(self, locale) -> Dict[str, List[str]]:
        """Phrases per category for one locale, or the union over several
        (a list): a code-switched message is checked against every
        language it may contain."""
        locales = [locale] if isinstance(locale, str) else list(locale)
        out: Dict[str, List[str]] = {}
        for category, phrases in self.categories.items():
            merged: List[str] = []
            for loc in locales:
                for phrase in phrases.get(loc, []) or []:
                    if phrase not in merged:
                        merged.append(phrase)
            out[category] = merged
        return out


@dataclass(frozen=True)
class AccusationTerms:
    epithets: Dict[str, List[str]]
    mob_language: Dict[str, List[str]]
    # "<Name> is a thief" (en-NG: is/are) and "<Name> je ole" (yo: je).
    copulas: Dict[str, List[str]] = field(default_factory=dict)
    # "ole ni Bello" (yo): the accusation comes before the name.
    inverted_copulas: Dict[str, List[str]] = field(default_factory=dict)

    @staticmethod
    def _merged(table: Dict[str, List[str]], locale) -> List[str]:
        locales = [locale] if isinstance(locale, str) else list(locale)
        out: List[str] = []
        for loc in locales:
            for item in table.get(loc, []) or []:
                if item not in out:
                    out.append(item)
        return out

    def epithets_for(self, locale) -> List[str]:
        return self._merged(self.epithets, locale)

    def mob_language_for(self, locale) -> List[str]:
        return self._merged(self.mob_language, locale)

    def copulas_for(self, locale) -> List[str]:
        return self._merged(self.copulas, locale) or ["is", "are"]

    def inverted_copulas_for(self, locale) -> List[str]:
        return self._merged(self.inverted_copulas, locale)


@dataclass(frozen=True)
class LocaleMarkers:
    # Letters only this language uses, and common words of it (folded:
    # lower case, tone marks removed). See config/locales.yaml.
    letters: frozenset
    words: frozenset
    min_distinct_words: int
    display_name: str = ""


@dataclass(frozen=True)
class AppConfig:
    communities: Dict[str, Community]
    patterns: List[PatternDefinition]
    pattern_min_score: int
    redaction_terms: RedactionTerms
    accusation_terms: AccusationTerms
    # Optional (config/locales.yaml). Empty means every message is read in
    # its community's default locale, as before.
    locale_markers: Dict[str, LocaleMarkers] = field(default_factory=dict)
    locale_names: Dict[str, str] = field(default_factory=dict)

    def all_locales(self, first=()) -> List[str]:
        """Every locale any config file knows, with `first` leading. The
        safety layers (redaction, accusation guard, protected-channel
        fallback) check every message against all of them, so a wrong
        language guess can never let identity content or an accusation
        through. It can only over-redact, which is the safe direction."""
        out: List[str] = [loc for loc in first if loc]
        pools = [self.locale_names.keys(), (c.locale for c in self.communities.values())]
        pools += [phrases.keys() for phrases in self.redaction_terms.categories.values()]
        pools += [self.accusation_terms.epithets.keys(), self.accusation_terms.mob_language.keys()]
        for pool in pools:
            for loc in pool:
                if loc not in out:
                    out.append(loc)
        return out

    def community_by_id(self, community_id: str) -> Optional[Community]:
        return self.communities.get(community_id)

    def community_by_inbound(self, inbound: str) -> Optional[Community]:
        """Resolve a community from the webhook 'to' address.

        This is the scalability seam: clustering scopes to a community
        because the inbound identifier told us which one, not because a
        reporter filled in a geo field.
        """
        for c in self.communities.values():
            if inbound in (c.normal_inbound, c.protected_inbound):
                return c
        return None

    def channel_for_inbound(self, community: Community, inbound: str) -> Optional[str]:
        if inbound == community.protected_inbound:
            return "protected"
        if inbound == community.normal_inbound:
            return "normal"
        return None


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def _merge_thresholds(default: dict, override: dict) -> dict:
    merged = copy.deepcopy(default)
    for section, values in (override or {}).items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section] = {**merged[section], **values}
        else:
            merged[section] = values
    return merged


def _build_thresholds(raw: dict) -> Thresholds:
    try:
        normal = raw["normal_channel"]
        protected = raw["protected_channel"]
        guard = raw["profiling_guard"]["max_redacted_fraction"]
        return Thresholds(
            normal_channel=NormalChannelThresholds(
                watch=SpanThreshold(**normal["watch"]),
                escalate=SpanThreshold(**normal["escalate"]),
            ),
            protected_channel=ProtectedChannelThreshold(**protected),
            profiling_guard_max_redacted_fraction=float(guard),
        )
    except KeyError as exc:
        raise ConfigError(f"thresholds.yaml missing key: {exc}") from exc


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    """Load and validate every config/*.yaml file into an AppConfig.

    Pass config_dir to load an alternate config tree (tests use this to
    prove that adding a community is a config-only change).
    """
    config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR

    communities_raw = _load_yaml(config_dir / "communities.yaml")
    thresholds_raw = _load_yaml(config_dir / "thresholds.yaml")
    patterns_raw = _load_yaml(config_dir / "patterns.yaml")
    redaction_raw = _load_yaml(config_dir / "redaction_terms.yaml")
    accusation_raw = _load_yaml(config_dir / "accusation_terms.yaml")

    communities: Dict[str, Community] = {}
    for row in communities_raw.get("communities", []):
        try:
            cid = row["id"]
            merged_threshold_raw = _merge_thresholds(thresholds_raw, row.get("thresholds") or {})
            communities[cid] = Community(
                id=cid,
                name=row["name"],
                locale=row["locale"],
                normal_inbound=row["normal_inbound"],
                protected_inbound=row["protected_inbound"],
                protected_recipients=[Recipient(**r) for r in row.get("protected_recipients", [])],
                desk_recipients=[Recipient(**r) for r in row.get("desk_recipients", [])],
                thresholds=_build_thresholds(merged_threshold_raw),
            )
        except KeyError as exc:
            raise ConfigError(f"communities.yaml row missing key {exc}: {row}") from exc

    if not communities:
        raise ConfigError("communities.yaml defines no communities")

    patterns = [
        PatternDefinition(
            id=p["id"],
            name=p["name"],
            locale_keywords=p.get("locale_keywords", {}),
            high_signal=bool(p.get("high_signal", False)),
            watch_override=SpanThreshold(**p["watch"]) if p.get("watch") else None,
            escalate_override=SpanThreshold(**p["escalate"]) if p.get("escalate") else None,
        )
        for p in patterns_raw.get("patterns", [])
    ]

    redaction_terms = RedactionTerms(categories=redaction_raw.get("categories", {}))
    accusation_terms = AccusationTerms(
        epithets=accusation_raw.get("epithets", {}),
        mob_language=accusation_raw.get("mob_language", {}),
        copulas=accusation_raw.get("copulas", {}),
        inverted_copulas=accusation_raw.get("inverted_copulas", {}),
    )

    locale_markers: Dict[str, LocaleMarkers] = {}
    locale_names: Dict[str, str] = {}
    locales_path = config_dir / "locales.yaml"
    if locales_path.exists():
        from app.textnorm import fold

        for code, row in (_load_yaml(locales_path).get("locales") or {}).items():
            row = row or {}
            locale_names[code] = row.get("display_name", code)
            detect = row.get("detect")
            if detect:
                locale_markers[code] = LocaleMarkers(
                    letters=frozenset(str(c).lower() for c in detect.get("letters", [])),
                    words=frozenset(fold(str(w)) for w in detect.get("words", [])),
                    min_distinct_words=int(detect.get("min_distinct_words", 3)),
                    display_name=locale_names[code],
                )

    return AppConfig(
        communities=communities,
        patterns=patterns,
        pattern_min_score=int(patterns_raw.get("min_score", 1)),
        redaction_terms=redaction_terms,
        accusation_terms=accusation_terms,
        locale_markers=locale_markers,
        locale_names=locale_names,
    )


_cached_config: Optional[AppConfig] = None


def get_config(force_reload: bool = False) -> AppConfig:
    """Process-wide cached config, loaded from DEFAULT_CONFIG_DIR."""
    global _cached_config
    if _cached_config is None or force_reload:
        _cached_config = load_config()
    return _cached_config
