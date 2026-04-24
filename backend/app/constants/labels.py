from __future__ import annotations

from typing import Final


FEATURE_KEYS: Final[tuple[str, ...]] = (
    "lockdown",
    "evacuation",
    "shelter",
    "secure",
    "request_help",
)

FEATURE_LABELS: Final[dict[str, str]] = {
    "lockdown": "Lockdown",
    "evacuation": "Evacuation",
    "shelter": "Shelter",
    "secure": "Secure Perimeter",
    "request_help": "Request Help",
}

_LEGACY_FEATURE_ALIASES: Final[dict[str, str]] = {
    "team_assist": "request_help",
    "team assist": "request_help",
    "request help": "request_help",
}


def normalize_feature_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return normalized
    # TODO: remove team_assist compatibility after migration complete.
    return _LEGACY_FEATURE_ALIASES.get(normalized, normalized)


def get_feature_label(key: str, school_id: str | None = None) -> str:
    canonical_key = normalize_feature_key(key)
    label = FEATURE_LABELS.get(canonical_key)
    if label is not None:
        return label
    # Future: look up per-school overrides using school_id.
    return key

