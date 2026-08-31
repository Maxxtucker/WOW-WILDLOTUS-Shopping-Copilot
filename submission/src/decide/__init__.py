"""Decide layer: jointly plan a ranked prefix and next clarification.

Input: SearchHit list, SessionState, top_k; response writeback uses candidate ASINs.
Output: {message, ask_attribute, recommendations, usage}, and session writeback.
Role: Dynamic Slate balances Hit, reciprocal rank, efficiency, and future
answer value, then writes the official response. See README.md.
"""

from .clarification import (
    Clarifier,
    DEFAULT_RECOMMENDATION_SCORE_WEIGHTS,
    DEFAULT_SLIDER_POSITION,
    Plan,
    RecommendationScoreWeights,
    ScoreAwarePlanner,
    hit_utility,
)
from .ranking import RankedCandidate, Ranker, normalize_probabilities
from .response import ResponseBuilder

__all__ = [
    "Clarifier",
    "Plan",
    "RankedCandidate",
    "Ranker",
    "ResponseBuilder",
    "ScoreAwarePlanner",
    "hit_utility",
    "RecommendationScoreWeights",
    "DEFAULT_RECOMMENDATION_SCORE_WEIGHTS",
    "DEFAULT_SLIDER_POSITION",
    "normalize_probabilities",
]
