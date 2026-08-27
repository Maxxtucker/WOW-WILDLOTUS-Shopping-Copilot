"""Purpose: observation package: extract then apply in a fixed order.

Input: SessionState, this turn's message.
Output: SessionState written category / constraints / override.
Role: the only parse-order entry inside understand. See README.md.
"""

from .classify import (
    CategoryHit,
    OverrideHit,
    colon_fallback,
    extract_category,
    extract_constraints,
    parse_override,
)
from .coordinator import ObservationCoordinator, observe

__all__ = [
    "CategoryHit",
    "ObservationCoordinator",
    "OverrideHit",
    "colon_fallback",
    "extract_category",
    "extract_constraints",
    "observe",
    "parse_override",
]
