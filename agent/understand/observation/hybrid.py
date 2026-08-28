"""Purpose: NLU observation first; regex after failed extracts or in regex mode.

Input: SessionState plus this turn's stripped message.
Output: ObservationExtract. Protocol-like phrasing is not a reason to skip the model.
Role: observe() writes state from this payload. Regex is the fallback, not a test hook.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.parsers import MATTERS_RE
from ..intention.parsers import (
    EXPLORING_RE,
    INITIAL_OTHER_RE,
    KEY_REQUIREMENT_RE,
    OVERRIDE_RE,
)
from ..mode import MODE_NLU, current_understand_mode
from .classify import extract_category, extract_constraints, parse_override
from .llm_nlu import extract_with_llm
from .schema import ObservationExtract

if TYPE_CHECKING:
    from ..state.session import SessionState

NLU_ATTEMPTS = 3


def regex_is_high_confidence(message: str) -> bool:
    """True when the utterance matches looking-for / matters / override templates.

    Diagnostic only. In nlu mode, hybrid_extract still calls the model.
    """

    return bool(
        KEY_REQUIREMENT_RE.match(message)
        or MATTERS_RE.search(message)
        or OVERRIDE_RE.search(message)
        or EXPLORING_RE.match(message)
        or INITIAL_OTHER_RE.match(message)
    )


def extract_from_regex(state: SessionState, message: str) -> ObservationExtract:
    constraints = tuple(extract_constraints(state, message))
    category_hit = extract_category(message)
    override = parse_override(message, gate_closed=not state.gate_open)
    return ObservationExtract(
        category=None if category_hit is None else category_hit.category,
        provisional_hint=None if category_hit is None else category_hit.provisional_hint,
        constraints=constraints,
        override=override is not None,
        override_value=None if override is None else override.new_value,
        source="regex",
    )


def hybrid_extract(state: SessionState, message: str) -> ObservationExtract:
    """NLU up to NLU_ATTEMPTS times when mode is nlu; else regex."""

    if current_understand_mode() == MODE_NLU:
        for _ in range(NLU_ATTEMPTS):
            llm_extract = extract_with_llm(state, message)
            if llm_extract is not None:
                return llm_extract
    return extract_from_regex(state, message)
