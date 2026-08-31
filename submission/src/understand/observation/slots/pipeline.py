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
from .attributes.category import cite_tokens, ground_category, surface_for_tags
from .merge import merge_or_attribute_slots
from .parse import coerce_is_hard, parse_constraint_item, parse_string_list
from .text import ground_surface
from .types import ConstraintSlot, GroundingFailures

MAX_REPAIR_ROUNDS = 3


def _category_payload_items(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("category")
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [item for item in raw if item not in (None, "")]
    return [raw]


def _category_surface(item: Any) -> object:
    if isinstance(item, dict):
        return item.get("surface") or item.get("value") or item.get("text")
    return item


def _category_canonical(item: Any) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return ()
    return parse_string_list(item.get("canonical") or item.get("catalog_tags"))


def category_item_is_grounded(item: Any, message: str) -> bool:
    """True when the row cites a span of ``message``."""

    return _cited_category_surface(item, message) is not None


def _cited_category_surface(item: Any, message: str) -> str | None:
    surface = str(_category_surface(item) or "")
    tags = _category_canonical(item)
    span = ground_category(surface, message)
    if span:
        return span
    return surface_for_tags(message, surface, *tags, *cite_tokens(surface, *tags))


def category_slots_from_payload(
    payload: Any, message: str
) -> tuple[str | None, list[ConstraintSlot]]:
    """Ground top-level category (string or list of {surface, canonical, is_hard}).

    ``surface`` must be a span of the original shopper sentence (the full
    label/tag, or a content token from them). Sidecar ``canonical`` tags are
    classify keys for probe. Rows with no cite are dropped.

    When several hard cited rows are present (tree L1/L2/L3), the extract
    summary is the last hard row — the most specific layer that cited.
    """

    slots: list[ConstraintSlot] = []
    last_hard: str | None = None
    last_any: str | None = None
    for item in _category_payload_items(payload):
        cited = _cited_category_surface(item, message)
        if not cited:
            continue
        tags = _category_canonical(item)
        is_hard = True
        if isinstance(item, dict):
            is_hard = coerce_is_hard(item.get("is_hard"))
        slots.append(
            ConstraintSlot(
                attribute="category",
                surface=cited,
                canonical=tags or None,
                is_hard=is_hard,
            )
        )
        last_any = cited
        if is_hard:
            last_hard = cited
    return last_hard or last_any, slots


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
    for item in _category_payload_items(payload):
        if not category_item_is_grounded(item, message):
            failures.category = True
            break
    if payload.get("provisional_hint") and ground_span(
        payload.get("provisional_hint"), message
    ) is None:
        failures.provisional_hint = True
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
    if repair.get("track") in VALID_TRACKS:
        merged["track"] = repair.get("track")
    if failures.constraints:
        kept_items = [
            item for item in raw_constraint_list(base) if item not in failures.constraints
        ]
        extra = raw_constraint_list(repair)
        merged["constraints"] = kept_items + extra
    return merged


def grounded_extract_from_payload(
    payload: Any,
    message: str,
    *,
    category_message: str | None = None,
) -> ObservationExtract:
    if not isinstance(payload, dict):
        return ObservationExtract(empty=True, source="llm")
    if payload.get("empty"):
        return ObservationExtract(empty=True, source="llm")

    cat_message = message if category_message is None else category_message
    _kept, _failed, slots = partition_constraints(payload, message)
    summary, category_slots = category_slots_from_payload(payload, cat_message)
    slots = merge_or_attribute_slots([*slots, *category_slots])
    surfaces = tuple(
        dict.fromkeys(slot.surface for slot in slots if slot.attribute != "category")
    )
    track = payload.get("track")
    if track not in VALID_TRACKS:
        track = None
    extract = ObservationExtract(
        category=summary,
        provisional_hint=ground_span(payload.get("provisional_hint"), message),
        constraints=surfaces,
        slots=tuple(slots),
        track=track,
        empty=False,
        source="llm",
    )
    if (
        not extract.category
        and not extract.provisional_hint
        and not extract.constraints
        and not extract.slots
    ):
        return ObservationExtract(empty=True, source="llm")
    return extract
