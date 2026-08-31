"""Purpose: convert retrieval scores into positive deterministic ranking weights.

Input: SearchHit list (uses hit.score).
Output: [(parent_asin, weight), ...].
Role: use temperature 0.12 for ordinary scores and an observed-range
temperature for smaller weighted-RRF scores; neither path claims calibrated
probabilities.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...retrieve.catalog.types import SearchHit

BELIEF_TEMPERATURE = 0.12
FUSED_MIN_TEMPERATURE = 0.0025
FUSED_MAX_TEMPERATURE = 0.02


def belief_temperature(hits: list[SearchHit]) -> tuple[float, bool]:
    """Return the exact deterministic-belief temperature and fused flag."""

    if not hits:
        return BELIEF_TEMPERATURE, False
    maximum = max(hit.score for hit in hits)
    minimum = min(hit.score for hit in hits)
    fused = any(
        reason.startswith("route:")
        for hit in hits
        for reason in hit.reasons
    )
    if not fused:
        return BELIEF_TEMPERATURE, False
    spread = max(0.0, maximum - minimum)
    return (
        min(
            FUSED_MAX_TEMPERATURE,
            max(FUSED_MIN_TEMPERATURE, spread / 4.0),
        ),
        True,
    )


def belief_from_hits(hits: list[SearchHit]) -> list[tuple[str, float]]:
    """Temperature-scaled scores used as unnormalized ranking weights.

    A low-capacity temperature transform is deliberate: only ordering is
    needed for ranking, while a flatter distribution prevents the planner
    from treating small hand-score differences as certainty.
    """

    if not hits:
        return []
    maximum = max(hit.score for hit in hits)
    temperature, _fused = belief_temperature(hits)
    # The structured score is often constant within an exact-signature
    # bucket.  Temperature 0.12 turns the weak popularity/quality prior
    # into useful ordering without claiming that the raw score is a
    # calibrated probability.
    return [
        (hit.parent_asin, math.exp((hit.score - maximum) / temperature))
        for hit in hits
    ]
