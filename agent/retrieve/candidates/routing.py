"""Purpose: Buying vs Browsing retrieval weights and truncation.

Input: SessionState.intention (router-labeled; never an evaluator scenario label).
Output: TrackRouting consumed by retrieve_candidates.
Role: score weights and hit caps. Hard intersection lives on the router probe.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..catalog.types import SearchWeights

BUYING_LIMIT = 150
BROWSING_LIMIT = 500
DEFAULT_LIMIT = 500
DEFAULT_CANDIDATE_LIMIT = 1_500

BUYING_WEIGHTS = SearchWeights(
    lexical=0.4,
    required=6.0,
    category=4.0,
    missing_required=-0.5,
)
BROWSING_WEIGHTS = SearchWeights(
    lexical=1.6,
    required=2.5,
    category=2.0,
    missing_required=-0.1,
)


@dataclass(frozen=True, slots=True)
class TrackRouting:
    weights: SearchWeights
    limit: int
    exact_first: bool
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT


def routing_for(intention: str | None) -> TrackRouting:
    """Unset intention keeps the historical exact-first cap of 500."""

    if intention in {"buying", "override"}:
        return TrackRouting(BUYING_WEIGHTS, BUYING_LIMIT, exact_first=True)
    if intention == "browsing":
        return TrackRouting(BROWSING_WEIGHTS, BROWSING_LIMIT, exact_first=True)
    return TrackRouting(SearchWeights(), DEFAULT_LIMIT, exact_first=True)
