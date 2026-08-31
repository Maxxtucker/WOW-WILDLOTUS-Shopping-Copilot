"""Purpose: observation package: extract this turn into turn_delta.

Input: SessionState, this turn's message.
Output: state.turn_delta. Constraints are committed by the intention router.
Role: the only parse-order entry inside understand. See README.md.
"""

from .classify import (
    CategoryHit,
    OverrideHit,
    colon_fallback,
    extract_category,
    extract_constraints,
    extract_new_need,
    parse_override,
)
from .coordinator import ObservationCoordinator, observe
from .hybrid import hybrid_extract
from .schema import ObservationExtract, infer_track, parse_observation_payload, span_grounded
from .slots import ConstraintSlot

__all__ = [
    "CategoryHit",
    "ConstraintSlot",
    "ObservationCoordinator",
    "ObservationExtract",
    "OverrideHit",
    "colon_fallback",
    "extract_category",
    "extract_constraints",
    "extract_new_need",
    "hybrid_extract",
    "infer_track",
    "observe",
    "parse_observation_payload",
    "parse_override",
    "span_grounded",
]
