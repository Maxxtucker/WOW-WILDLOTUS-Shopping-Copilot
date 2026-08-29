"""Purpose: identify slots by (attribute, value) and split multi-canonical rows.

Input: grounded ConstraintSlot rows from one extract or a later turn.
Output: one row per (attribute, value_id). Same value later overwrites hardness.
Role: alternatives from one utterance become separate rows so hard/soft can coexist.
"""

from __future__ import annotations

from dataclasses import replace

from .text import fold_key
from .types import ConstraintSlot


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


def slot_value_id(slot: ConstraintSlot) -> str:
    """Identity for upsert: first canonical, else surface."""

    values = slot_or_values(slot)
    if values:
        return fold_key(values[0])
    return fold_key(slot.surface)


def slot_identity(slot: ConstraintSlot) -> tuple[str, str]:
    return (slot.attribute, slot_value_id(slot))


def split_value_rows(slot: ConstraintSlot) -> list[ConstraintSlot]:
    """One row per canonical (or surface) so hardness can change per value."""

    values = slot.canonical
    if values and len(values) > 1:
        return [replace(slot, canonical=(value,)) for value in values]
    return [slot]


def merge_or_slot(left: ConstraintSlot, right: ConstraintSlot) -> ConstraintSlot:
    """Kept for tests that union two same-attribute rows. Prefer split_value_rows."""

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
        is_hard=right.is_hard,
    )


def merge_or_attribute_slots(
    slots: list[ConstraintSlot] | tuple[ConstraintSlot, ...],
) -> list[ConstraintSlot]:
    """Dedup by (attribute, value_id). Later rows overwrite earlier ones."""

    result: list[ConstraintSlot] = []
    index: dict[tuple[str, str], int] = {}
    for slot in slots:
        for row in split_value_rows(slot):
            key = slot_identity(row)
            existing = index.get(key)
            if existing is None:
                index[key] = len(result)
                result.append(row)
            else:
                result[existing] = row
    return result
