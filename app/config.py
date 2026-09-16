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

    def keywords_for(self, locale: str) -> List[str]:
        return self.locale_keywords.get(locale, [])


@dataclass(frozen=True)
class RedactionTerms:
    # category -> locale -> list of phrases
    categories: Dict[str, Dict[str, List[str]]]

    def terms_for(self, locale: str) -> Dict[str, List[str]]:
        return {
            category: phrases.get(locale, [])
            for category, phrases in self.categories.items()
        }


@dataclass(frozen=True)
class AccusationTerms:
    epithets: Dict[str, List[str]]
    mob_language: Dict[str, List[str]]

    def epithets_for(self, locale: str) -> List[str]:
        return self.epithets.get(locale, [])

    def mob_language_for(self, locale: str) -> List[str]:
        return self.mob_language.get(locale, [])


@dataclass(frozen=True)
class AppConfig:
    communities: Dict[str, Community]
    patterns: List[PatternDefinition]
    pattern_min_score: int
    redaction_terms: RedactionTerms
    accusation_terms: AccusationTerms

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
        )
        for p in patterns_raw.get("patterns", [])
    ]

    redaction_terms = RedactionTerms(categories=redaction_raw.get("categories", {}))
    accusation_terms = AccusationTerms(
        epithets=accusation_raw.get("epithets", {}),
        mob_language=accusation_raw.get("mob_language", {}),
    )

    return AppConfig(
        communities=communities,
        patterns=patterns,
        pattern_min_score=int(patterns_raw.get("min_score", 1)),
        redaction_terms=redaction_terms,
        accusation_terms=accusation_terms,
    )


_cached_config: Optional[AppConfig] = None


def get_config(force_reload: bool = False) -> AppConfig:
    """Process-wide cached config, loaded from DEFAULT_CONFIG_DIR."""
    global _cached_config
    if _cached_config is None or force_reload:
        _cached_config = load_config()
    return _cached_config
