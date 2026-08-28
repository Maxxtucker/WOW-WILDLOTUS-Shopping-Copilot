"""Purpose: frozen NLU payload shared by regex extractors and the optional local model.

Input: model/regex fields plus the raw user message for span checks.
Output: ObservationExtract aligned with CategoryHit, constraint strings, and OverrideHit.
Role: LLM slots store mapped canonicals; grounding still checks shopper surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ...domain import canonical

if TYPE_CHECKING:
    from .slots import ConstraintSlot

TRACK_BUYING = "buying"
TRACK_BROWSING = "browsing"
VALID_TRACKS = frozenset({TRACK_BUYING, TRACK_BROWSING})
ExtractSource = Literal["regex", "llm"]


@dataclass(frozen=True)
class ObservationExtract:
    """Structured observation for one user message. Does not write SessionState."""

    category: str | None = None
    provisional_hint: str | None = None
    constraints: tuple[str, ...] = ()
    slots: tuple[ConstraintSlot, ...] = ()
    override: bool = False
    override_value: str | None = None
    track: str | None = None
    empty: bool = False
    source: ExtractSource = "regex"
    repair_rounds: int = 0


def span_grounded(value: str, message: str) -> bool:
    """True when ``value`` is a copied span of ``message`` (raw or canonical)."""

    cleaned = value.strip()
    if not cleaned:
        return False
    if cleaned.casefold() in message.casefold():
        return True
    needle = canonical(cleaned)
    haystack = canonical(message)
    return bool(needle) and needle in haystack


def ground_span(value: object, message: str) -> str | None:
    """Return a stripped span if it appears in the message; otherwise None."""

    if value is None:
        return None
    cleaned = str(value).strip(" \t\n.;")
    if not cleaned:
        return None
    if span_grounded(cleaned, message):
        return cleaned
    return None


def infer_track(extract: ObservationExtract, *, locked: bool = False) -> str | None:
    """Infer Buying vs Browsing from language evidence, not evaluator labels."""

    if extract.track in VALID_TRACKS:
        return extract.track
    if locked or extract.constraints or extract.override:
        return TRACK_BUYING
    if extract.provisional_hint or extract.category:
        return TRACK_BROWSING
    return None


def parse_observation_payload(payload: Any, message: str) -> ObservationExtract:
    """Coerce a JSON object into ObservationExtract and drop ungrounded spans."""

    from .slots import grounded_extract_from_payload

    return grounded_extract_from_payload(payload, message)
