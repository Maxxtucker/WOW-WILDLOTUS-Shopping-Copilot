"""Purpose: union OR-attribute slots that share an attribute name.

Input: grounded ConstraintSlot rows from one extract or a later turn.
Output: at most one slot per color/material/style/brand/feature/use_case/other.
Role: alternatives are a list on one slot; size and budget stay separate rows.
"""

from __future__ import annotations

from .text import fold_key
from .types import ConstraintSlot, OR_ATTRIBUTES


def union_values(*groups: tuple[str, ...] | None) -> tuple[str, ...] | None:
    items: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for value in group:
            key = fold_key(value)
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(value)
    return tuple(items) if items else None


def slot_or_values(slot: ConstraintSlot) -> tuple[str, ...]:
    if slot.canonical:
        return slot.canonical
    cleaned = slot.surface.strip()
    return (cleaned,) if cleaned else ()


def merge_or_slot(left: ConstraintSlot, right: ConstraintSlot) -> ConstraintSlot:
    """Combine two same-attribute OR slots. Surfaces are joined when they differ."""

    values = union_values(slot_or_values(left), slot_or_values(right))
    surfaces: list[str] = []
    for surface in (left.surface, right.surface):
        cleaned = surface.strip()
        if cleaned and fold_key(cleaned) not in {fold_key(item) for item in surfaces}:
            surfaces.append(cleaned)
    surface = "; ".join(surfaces) if surfaces else left.surface
    return ConstraintSlot(
        attribute=left.attribute,
        surface=surface,
        canonical=values,
        amount=left.amount if left.amount is not None else right.amount,
        op=left.op or right.op,
        system=left.system or right.system,
        kind=left.kind or right.kind,
        unit=left.unit or right.unit,
        length=left.length if left.length is not None else right.length,
        width=left.width if left.width is not None else right.width,
        height=left.height if left.height is not None else right.height,
    )


def merge_or_attribute_slots(
    slots: list[ConstraintSlot] | tuple[ConstraintSlot, ...],
) -> list[ConstraintSlot]:
    """Collapse same-attribute OR rows from one extract into one slot each."""

    result: list[ConstraintSlot] = []
    index: dict[str, int] = {}
    for slot in slots:
        if slot.attribute in OR_ATTRIBUTES:
            existing = index.get(slot.attribute)
            if existing is None:
                index[slot.attribute] = len(result)
                result.append(slot)
            else:
                result[existing] = merge_or_slot(result[existing], slot)
            continue
        result.append(slot)
    return result
