"""Purpose: shifted softmax of retrieval scores at temperature 0.12, as unnormalized quality.

Input: SearchHit list (uses hit.score).
Output: [(parent_asin, weight), ...].
Role: structured scores in an exact bucket are often identical; this only spreads the popularity prior and does not claim calibrated probabilities.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...retrieve.catalog.types import SearchHit

BELIEF_TEMPERATURE = 0.12
FUSED_MIN_TEMPERATURE = 0.0025
FUSED_MAX_TEMPERATURE = 0.02


def belief_from_hits(hits: list[SearchHit]) -> list[tuple[str, float]]:
    """Temperature-scaled scores used as unnormalized ranking weights.

    A low-capacity temperature transform is deliberate: only ordering is
    needed for ranking, while a flatter distribution prevents the planner
    from treating small hand-score differences as certainty.
    """

    if not hits:
        return []
    maximum = max(hit.score for hit in hits)
    minimum = min(hit.score for hit in hits)
    fused = any(
        reason.startswith("route:")
        for hit in hits
        for reason in hit.reasons
    )
    temperature = BELIEF_TEMPERATURE
    if fused:
        # Reciprocal-rank fusion scores live around 1/(60 + rank), two orders
        # of magnitude below the structured catalog score.  Reusing the
        # structured-score temperature makes hundreds of results look nearly
        # equiprobable and causes Dynamic Slate to overvalue wide slates.
        # Scale the temperature to the observed fused-score range while
        # retaining conservative lower/upper bounds.
        spread = max(0.0, maximum - minimum)
        temperature = min(
            FUSED_MAX_TEMPERATURE,
            max(FUSED_MIN_TEMPERATURE, spread / 4.0),
        )
    # The structured score is often constant within an exact-signature
    # bucket.  Temperature 0.12 turns the weak popularity/quality prior
    # into useful ordering without claiming that the raw score is a
    # calibrated probability.
    return [
        (hit.parent_asin, math.exp((hit.score - maximum) / temperature))
        for hit in hits
    ]
