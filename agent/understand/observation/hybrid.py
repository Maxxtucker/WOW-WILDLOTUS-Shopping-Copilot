"""Purpose: NLU observation first; regex after failed extracts or in regex mode.

Input: SessionState plus this turn's stripped message.
Output: ObservationExtract. Protocol-like phrasing is not a reason to skip the model.
Role: observe() stores this payload as turn_delta. Regex is the fallback, not a test hook.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes.parsers import MATTERS_RE
from .patterns import (
    EXPLORING_RE,
    INITIAL_OTHER_RE,
    KEY_REQUIREMENT_RE,
    OVERRIDE_RE,
)
from ...domain import classify_constraint
from ...progress import skip_nodes, UNDERSTAND_NLU_NODES
from ..mode import MODE_NLU, current_understand_mode
from .classify import extract_category, extract_constraints
from .llm_nlu import extract_with_llm
from .schema import ObservationExtract
from .slots.types import ConstraintSlot

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
    category = None if category_hit is None else category_hit.category
    hint = None if category_hit is None else category_hit.provisional_hint
    slots: list[ConstraintSlot] = []
    if category:
        slots.append(
            ConstraintSlot(attribute="category", surface=category, is_hard=True)
        )
    if hint:
        slots.append(
            ConstraintSlot(
                attribute=classify_constraint(hint),
                surface=hint,
                is_hard=False,
            )
        )
    for piece in constraints:
        slots.append(
            ConstraintSlot(
                attribute=classify_constraint(piece),
                surface=piece,
                is_hard=True,
            )
        )
    return ObservationExtract(
        category=category,
        provisional_hint=hint,
        constraints=constraints,
        slots=tuple(slots),
        source="regex",
    )


def hybrid_extract(state: SessionState, message: str) -> ObservationExtract:
    """NLU up to NLU_ATTEMPTS times when mode is nlu; else regex."""

    if current_understand_mode() == MODE_NLU:
        for _ in range(NLU_ATTEMPTS):
            llm_extract = extract_with_llm(state, message)
            if llm_extract is not None:
                return llm_extract
    skip_nodes("understand", *UNDERSTAND_NLU_NODES)
    return extract_from_regex(state, message)
