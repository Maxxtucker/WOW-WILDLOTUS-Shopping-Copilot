"""Purpose: process-wide understand extract mode (nlu vs regex).

Input: Agent keyword, configure_understand, or environment variables.
Output: current_understand_mode() is nlu or regex.
Role: hybrid_extract branches on this. Agent nlu startup starts the LLM runtime.
"""

from __future__ import annotations

import os

MODE_NLU = "nlu"
MODE_REGEX = "regex"
VALID_MODES = frozenset({MODE_NLU, MODE_REGEX})
_FALSE = {"0", "false", "no", "off"}

_configured: str | None = None


def _normalize(value: str) -> str:
    mode = value.strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(
            f"understand_mode must be {MODE_NLU!r} or {MODE_REGEX!r}, got {value!r}"
        )
    return mode


def resolve_understand_mode(explicit: str | None = None) -> str:
    """Resolve mode. Explicit argument wins, then env, then default nlu."""

    if explicit is not None:
        return _normalize(explicit)
    env_mode = os.environ.get("AGENT_UNDERSTAND_MODE", "").strip()
    if env_mode:
        return _normalize(env_mode)
    nlu_flag = os.environ.get("AGENT_NLU_ENABLED", "").strip().lower()
    if nlu_flag in _FALSE:
        return MODE_REGEX
    return MODE_NLU


def configure_understand(mode: str) -> str:
    """Pin the process-wide mode. Agent and tests call this."""

    global _configured
    _configured = _normalize(mode)
    return _configured


def current_understand_mode() -> str:
    if _configured is not None:
        return _configured
    return resolve_understand_mode(None)


def reset_understand_mode() -> None:
    """Clear the pin so later resolve uses env again. Tests only."""

    global _configured
    _configured = None
