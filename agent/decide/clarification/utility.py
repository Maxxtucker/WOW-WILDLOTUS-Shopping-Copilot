"""Purpose: runtime recommendation utility and user-selectable HitRate/MRR weights.

Input: turn, rank, and an optional immutable session weight object.
Output: one-hit utility used by clarification planners.
Role: redistribute the fixed recommendation budget for the live chat only.

The official evaluator keeps its fixed ``0.50 / 0.30 / 0.20`` composite. The
runtime planner uses the same decomposition by default, while a chat user may
move a pre-conversation preference slider that redistributes the fixed 0.80
recommendation budget between HitRate and MRR.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


RECOMMENDATION_BUDGET = 0.80
EFFICIENCY_WEIGHT = 0.20
DEFAULT_SLIDER_POSITION = 34.375


@dataclass(frozen=True, slots=True)
class RecommendationScoreWeights:
    """Weights for the runtime planner's per-hit utility."""

    hitrate_weight: float = 0.50
    mrr_weight: float = 0.30
    efficiency_weight: float = EFFICIENCY_WEIGHT

    def __post_init__(self) -> None:
        try:
            values = tuple(
                float(value)
                for value in (
                    self.hitrate_weight,
                    self.mrr_weight,
                    self.efficiency_weight,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("recommendation score weights must be numeric") from exc
        if not all(math.isfinite(value) for value in values):
            raise ValueError("recommendation score weights must be finite")
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("recommendation score weights must be in [0, 1]")
        object.__setattr__(self, "hitrate_weight", values[0])
        object.__setattr__(self, "mrr_weight", values[1])
        object.__setattr__(self, "efficiency_weight", values[2])
        if not math.isclose(
            self.hitrate_weight + self.mrr_weight,
            RECOMMENDATION_BUDGET,
            abs_tol=1e-9,
        ):
            raise ValueError("HitRate and MRR weights must sum to 0.80")
        if not math.isclose(
            self.efficiency_weight,
            EFFICIENCY_WEIGHT,
            abs_tol=1e-9,
        ):
            raise ValueError("efficiency weight is fixed at 0.20")

    @classmethod
    def from_slider_position(cls, position: object) -> "RecommendationScoreWeights":
        """Map a 0..100 slider position to the 9:1 .. 1:9 preference range."""

        if isinstance(position, bool):
            raise ValueError("slider position must be a finite number")
        try:
            value = float(position)
        except (TypeError, ValueError) as exc:
            raise ValueError("slider position must be a finite number") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError("slider position must be between 0 and 100")
        if value == 0.0:
            return cls(hitrate_weight=0.72, mrr_weight=0.08)
        if value == 100.0:
            return cls(hitrate_weight=0.08, mrr_weight=0.72)
        if value == DEFAULT_SLIDER_POSITION:
            return cls()
        progress = value / 100.0
        hitrate_share = 0.90 - 0.80 * progress
        hitrate_weight = RECOMMENDATION_BUDGET * hitrate_share
        return cls(
            hitrate_weight=hitrate_weight,
            mrr_weight=RECOMMENDATION_BUDGET - hitrate_weight,
        )


DEFAULT_RECOMMENDATION_SCORE_WEIGHTS = RecommendationScoreWeights()


def hit_utility(
    turn: int,
    rank: int,
    weights: RecommendationScoreWeights | None = None,
) -> float:
    """Per-session contribution used by the runtime planner."""

    scoring = weights or DEFAULT_RECOMMENDATION_SCORE_WEIGHTS
    return (
        scoring.hitrate_weight
        + scoring.mrr_weight / rank
        + scoring.efficiency_weight * (11 - turn) / 10.0
    )
