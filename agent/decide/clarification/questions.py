"""Purpose: list still-informative ask_attribute values and customer-facing question templates.

Input: SessionState, candidates, answer_signature callback.
Output: askable attributes (including None = ask nothing); explain_question returns natural language.
Role: skip already-asked typed attributes and empty partitions; other may repeat.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from ...domain import QUESTION_ATTRIBUTES
from .types import NO_ADDITIONAL

if TYPE_CHECKING:
    from ..ranking.normalize import RankedCandidate
    from ...understand.state.session import SessionState


def eligible_questions(
    state: SessionState,
    candidates: Sequence[RankedCandidate],
    answer_signature: Callable[[str, str], tuple[str, ...]],
    max_planning_candidates: int,
) -> list[str | None]:
    if state.turn >= 10:
        return [None]
    result: list[str | None] = [None]
    for attribute in QUESTION_ATTRIBUTES:
        signatures = {
            answer_signature(item.parent_asin, attribute)
            for item in candidates[:max_planning_candidates]
        }
        informative = {value for value in signatures if value != NO_ADDITIONAL}
        if not informative:
            continue
        # Repeated ``other`` is useful because it reveals the next pair of
        # undisclosed constraints. Already-asked and already-locked typed
        # attributes are not repeated.
        if attribute != "other" and attribute in state.asked:
            continue
        if attribute != "other" and any(
            slot.attribute == attribute for slot in state.typed_constraints
        ):
            continue
        result.append(attribute)
    return result


def explain_question(attribute: str | None) -> str:
    templates = {
        "material": "Do you have a preferred material?",
        "color": "Which color would you prefer?",
        "size": "Do you have a size or fit requirement?",
        "style": "What style or fit should I prioritize?",
        "budget": "What budget range should I use?",
        "feature": "Which product feature matters most to you?",
        "use_case": "What will you mainly use the product for?",
        "other": "What other requirements matter most to you?",
        "category": "Which product category should I focus on?",
        "brand": "Do you have a preferred brand?",
    }
    return templates.get(attribute, "I have enough information to refine the shortlist.")
