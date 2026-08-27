"""Decide layer: posterior rank, pick the most distinguishing question, assemble the official response.

Input: SearchHit list, SessionState, top_k.
Output: {message, ask_attribute, recommendations, usage}, and session writeback.
Role: hit at rank-1 as early as possible within 10 turns. See README.md.
"""

from .clarification import Clarifier, Plan, ScoreAwarePlanner, hit_utility
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
    "normalize_probabilities",
]
