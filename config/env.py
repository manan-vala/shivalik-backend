"""
Tiny typed accessors over ``os.environ``.

Deliberately not a dependency: the project needs four coercions (str, bool,
int, list) and nothing else. Keeping it here means ``settings.py`` reads as a
flat list of decisions rather than a wall of ``os.environ.get`` calls.

Every accessor treats an empty string as "unset" so that a blank line in
``.env`` (``DB_PASSWORD=``) falls back to the default instead of silently
configuring an empty value.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

_UNSET = object()


def env(name: str, default=_UNSET) -> str:
    """Return ``name`` from the environment, or ``default`` if it is unset."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if default is _UNSET:
        raise ImproperlyConfigured(f"Required environment variable {name!r} is not set.")
    return default


def env_bool(name: str, default: bool) -> bool:
    """Parse a boolean. Accepts 1/true/yes/on and 0/false/no/off, any case."""
    raw = env(name, "")
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ImproperlyConfigured(
        f"Environment variable {name!r} must be a boolean, got {raw!r}."
    )


def env_int(name: str, default: int) -> int:
    raw = env(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"Environment variable {name!r} must be an integer, got {raw!r}."
        ) from exc


def env_list(name: str, default=None):
    """Parse a comma-separated list, dropping blanks and surrounding spaces."""
    raw = env(name, "")
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]
