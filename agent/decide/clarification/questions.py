"""Purpose: list still-informative ask_attribute values and customer-facing question templates.

Input: SessionState, candidates, answer_signature callback.
Output: askable attributes (including None = ask nothing); explain_question returns natural language.
Role: skip exhausted questions and empty partitions; other may repeat only after useful evidence.
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
    # With an empty retrieval head, retain high-coverage recovery questions.
    # Dynamic Slate's tail model decides whether asking one is worth more than
    # returning an empty recommendation list.
    if not candidates:
        for attribute in ("feature", "material", "color", "other"):
            if attribute in state.asked:
                continue
            result.append(attribute)
        return result
    for attribute in QUESTION_ATTRIBUTES:
        signatures = {
            answer_signature(item.parent_asin, attribute)
            for item in candidates[:max_planning_candidates]
        }
        informative = {value for value in signatures if value != NO_ADDITIONAL}
        if not informative:
            continue
        # Repeated ``other`` can reveal another pair of constraints, but it is
        # exhausted after an explicit no-additional-preference observation.
        # Already-asked and already-locked typed attributes are not repeated.
        if attribute == "other" and (
            state.disclosure_empty is True or attribute in state.asked
        ):
            continue
        if attribute != "other" and attribute in state.asked:
            continue
        if attribute != "other" and any(
            slot.attribute == attribute and slot.is_hard
            for slot in state.typed_constraints
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
