"""Purpose: ranking package: SearchHit → RankedCandidate posterior.

Input: SearchHit list.
Output: RankedCandidate list.
Role: pipeline stage 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .belief import BELIEF_TEMPERATURE, belief_from_hits
from .normalize import RankedCandidate, normalize_probabilities

if TYPE_CHECKING:
    from ...retrieve.catalog.types import SearchHit


class Ranker:
    """Stage 6: softmax belief over the current candidate pool."""

    def apply(self, hits: list[SearchHit]) -> list[RankedCandidate]:
        return normalize_probabilities(belief_from_hits(hits))


__all__ = [
    "BELIEF_TEMPERATURE",
    "RankedCandidate",
    "Ranker",
    "belief_from_hits",
    "normalize_probabilities",
]
