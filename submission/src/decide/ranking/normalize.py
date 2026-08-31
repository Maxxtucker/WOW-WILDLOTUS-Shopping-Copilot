"""Purpose: normalize positive weights into a RankedCandidate posterior and sort by score.

Input: [(parent_asin, weight), ...].
Output: RankedCandidate list whose probabilities sum to 1.
Role: the planner uses p(d) for expected utility.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedCandidate:
    parent_asin: str
    score: float
    probability: float


def normalize_probabilities(items: Sequence[tuple[str, float]]) -> list[RankedCandidate]:
    if not items:
        return []
    finite = [(asin, max(float(weight), 1e-12)) for asin, weight in items]
    total = sum(weight for _, weight in finite)
    return [
        RankedCandidate(asin, weight, weight / total)
        for asin, weight in sorted(finite, key=lambda item: (-item[1], item[0]))
    ]
