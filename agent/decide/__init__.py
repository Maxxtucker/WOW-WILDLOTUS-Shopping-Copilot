"""Decide layer: posterior rank, pick the most distinguishing question, assemble the official response.

Input: SearchHit list, SessionState, top_k; response writeback uses candidate ASINs.
Output: {message, ask_attribute, recommendations, usage}, and session writeback.
Role: hit at rank-1 as early as possible within 10 turns. See README.md.
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
