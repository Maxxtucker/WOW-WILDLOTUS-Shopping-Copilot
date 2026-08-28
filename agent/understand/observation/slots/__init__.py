"""Purpose: typed NLU constraint slots, per-attribute grounding, and repair merge.

Input: raw LLM constraint items plus the user message.
Output: grounded ConstraintSlot values, or failed raw items for repair.
Role: facade. Each of the ten attributes lives in attributes/; this re-exports the API.
"""

from .attributes.color import CLOSED_COLORS, CLOSED_COLOR_SET
from .attributes.material import CLOSED_MATERIAL_SET
from .attributes.size import (
    APPAREL_LETTERS,
    SIZE_KINDS,
    SIZE_SYSTEMS,
    SIZE_UNITS,
)
from .merge import merge_or_attribute_slots, merge_or_slot
from .pipeline import (
    MAX_REPAIR_ROUNDS,
    collect_failures,
    ground_constraint_item,
    grounded_extract_from_payload,
    merge_repair_payload,
    partition_constraints,
)
from .types import ConstraintSlot, GroundingFailures, OR_ATTRIBUTES

__all__ = [
    "APPAREL_LETTERS",
    "CLOSED_COLORS",
    "CLOSED_COLOR_SET",
    "CLOSED_MATERIAL_SET",
    "ConstraintSlot",
    "GroundingFailures",
    "MAX_REPAIR_ROUNDS",
    "OR_ATTRIBUTES",
    "SIZE_KINDS",
    "SIZE_SYSTEMS",
    "SIZE_UNITS",
    "collect_failures",
    "ground_constraint_item",
    "grounded_extract_from_payload",
    "merge_or_attribute_slots",
    "merge_or_slot",
    "merge_repair_payload",
    "partition_constraints",
]
