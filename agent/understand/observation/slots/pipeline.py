"""Purpose: parse, surface-ground, then dispatch each constraint to its attribute.

Input: raw LLM payload plus the user message.
Output: grounded ConstraintSlot values, failures, and ObservationExtract.
Role: orchestration only. Attribute rules live in attributes/*.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ....domain import canonical
from ..schema import ObservationExtract, VALID_TRACKS, ground_span
from .attributes import ground_attribute
from .attributes.category import ground_category
from .merge import merge_or_attribute_slots
from .parse import parse_constraint_item
from .text import ground_surface
from .types import ConstraintSlot, GroundingFailures

MAX_REPAIR_ROUNDS = 3


def ground_constraint_item(item: Any, message: str) -> ConstraintSlot | None:
    parsed = parse_constraint_item(item)
    if parsed is None:
        return None
    grounded_alts: list[str] = []
    for alt in parsed.alt_surfaces:
        grounded = ground_surface(
            alt, message, amount=parsed.amount, extras=parsed.extras
        )
        if grounded is None:
            return None
        grounded_alts.append(grounded)
    primary: str | None = None
    if parsed.surface:
        primary = ground_surface(
            parsed.surface, message, amount=parsed.amount, extras=parsed.extras
        )
        if primary is None:
            return None
    elif grounded_alts:
        primary = ", ".join(dict.fromkeys(grounded_alts))
    if primary is None:
        return None
    parsed = replace(
        parsed,
        surface=primary,
        alt_surfaces=tuple(grounded_alts),
        extras=tuple(dict.fromkeys((*parsed.extras, *grounded_alts))),
    )
    return ground_attribute(parsed, primary, message)


def raw_constraint_list(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("constraints") or ()
    if isinstance(raw, str) or isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if item not in (None, "")]
    return []


def partition_constraints(
    payload: Any, message: str
) -> tuple[list[Any], list[Any], list[ConstraintSlot]]:
    kept: list[Any] = []
    failed: list[Any] = []
    slots: list[ConstraintSlot] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_constraint_list(payload):
        slot = ground_constraint_item(item, message)
        if slot is None:
            failed.append(item)
            continue
        key = (slot.attribute, canonical(slot.surface))
        kept.append(item)
        if key not in seen:
            seen.add(key)
            slots.append(slot)
    return kept, failed, merge_or_attribute_slots(slots)


def collect_failures(payload: Any, message: str) -> GroundingFailures:
    failures = GroundingFailures()
    if not isinstance(payload, dict) or payload.get("empty"):
        return failures
    if payload.get("category") and ground_category(
        payload.get("category"), message
    ) is None:
        failures.category = True
    if payload.get("provisional_hint") and ground_span(
        payload.get("provisional_hint"), message
    ) is None:
        failures.provisional_hint = True
    if payload.get("override_value") and ground_span(
        payload.get("override_value"), message
    ) is None:
        failures.override_value = True
    _kept, failed, _slots = partition_constraints(payload, message)
    failures.constraints = failed
    return failures


def merge_repair_payload(
    base: dict[str, Any],
    repair: dict[str, Any],
    failures: GroundingFailures,
) -> dict[str, Any]:
    """Replace only failed fields; keep already-grounded constraints."""

    merged = dict(base)
    if failures.category and "category" in repair:
        merged["category"] = repair.get("category")
    if failures.provisional_hint and "provisional_hint" in repair:
        merged["provisional_hint"] = repair.get("provisional_hint")
    if failures.override_value and "override_value" in repair:
        merged["override_value"] = repair.get("override_value")
    if "override" in repair:
        merged["override"] = repair.get("override")
    if repair.get("track") in VALID_TRACKS:
        merged["track"] = repair.get("track")
    if failures.constraints:
        kept_items = [
            item for item in raw_constraint_list(base) if item not in failures.constraints
        ]
        extra = raw_constraint_list(repair)
        merged["constraints"] = kept_items + extra
    return merged


def grounded_extract_from_payload(payload: Any, message: str) -> ObservationExtract:
    if not isinstance(payload, dict):
        return ObservationExtract(empty=True, source="llm")
    if payload.get("empty"):
        return ObservationExtract(empty=True, source="llm")

    _kept, _failed, slots = partition_constraints(payload, message)
    surfaces = tuple(dict.fromkeys(slot.surface for slot in slots))
    track = payload.get("track")
    if track not in VALID_TRACKS:
        track = None
    extract = ObservationExtract(
        category=ground_category(payload.get("category"), message),
        provisional_hint=ground_span(payload.get("provisional_hint"), message),
        constraints=surfaces,
        slots=tuple(slots),
        override=bool(payload.get("override")),
        override_value=ground_span(payload.get("override_value"), message),
        track=track,
        empty=False,
        source="llm",
    )
    if (
        not extract.category
        and not extract.provisional_hint
        and not extract.constraints
        and not extract.override
    ):
        return ObservationExtract(empty=True, source="llm")
    return extract
