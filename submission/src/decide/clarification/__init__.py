"""Purpose: clarification package: pick the most distinguishing attribute and how many products to show.

Input: SessionState, RankedCandidate, top_k.
Output: Plan and a possibly truncated slate.
Role: decide's core policy. See README.md.
"""

from .planner import ScoreAwarePlanner
from .dynamic_slate import (
    DynamicSlateAction,
    DynamicSlateBranch,
    DynamicSlateConfig,
    DynamicSlatePlanner,
    DynamicSlateState,
    DynamicSlateTransitionModel,
)
from .questions import eligible_questions, explain_question
from .slate import apply_sequential_gate
from .stage import Clarifier
from .types import NO_ADDITIONAL, Plan
from .utility import (
    DEFAULT_RECOMMENDATION_SCORE_WEIGHTS,
    DEFAULT_SLIDER_POSITION,
    RecommendationScoreWeights,
    hit_utility,
)

__all__ = [
    "NO_ADDITIONAL",
    "Clarifier",
    "DynamicSlateAction",
    "DynamicSlateBranch",
    "DynamicSlateConfig",
    "DynamicSlatePlanner",
    "DynamicSlateState",
    "DynamicSlateTransitionModel",
    "Plan",
    "ScoreAwarePlanner",
    "apply_sequential_gate",
    "eligible_questions",
    "explain_question",
    "hit_utility",
    "RecommendationScoreWeights",
    "DEFAULT_RECOMMENDATION_SCORE_WEIGHTS",
    "DEFAULT_SLIDER_POSITION",
]
