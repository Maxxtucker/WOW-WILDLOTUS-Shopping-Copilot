"""Purpose: partition candidates by predicted reply and estimate next-question Top-10 utility.

Input: residual candidates, attribute, next_turn, answer_signature.
Output: sum of terminal utilities over reply partitions (float).
Role: distinguishability is expected TechnicalScore, not entropy.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from .utility import hit_utility

if TYPE_CHECKING:
    from ..ranking.normalize import RankedCandidate


def terminal_value(candidates: Sequence[RankedCandidate], turn: int) -> float:
    return sum(
        item.probability * hit_utility(turn, rank)
        for rank, item in enumerate(candidates[:10], start=1)
    )


def future_value(
    residual: Sequence[RankedCandidate],
    attribute: str | None,
    next_turn: int,
    answer_signature: Callable[[str, str], tuple[str, ...]],
    max_planning_candidates: int,
) -> float:
    if not residual or next_turn > 10:
        return 0.0
    if attribute is None:
        return terminal_value(residual, next_turn)

    groups: dict[tuple[str, ...], list[RankedCandidate]] = defaultdict(list)
    for item in residual[:max_planning_candidates]:
        groups[answer_signature(item.parent_asin, attribute)].append(item)

    # Probabilities remain unconditional here.  Summing each branch's
    # top-10 terminal reward therefore already integrates branch mass.
    return sum(terminal_value(group, next_turn) for group in groups.values())
