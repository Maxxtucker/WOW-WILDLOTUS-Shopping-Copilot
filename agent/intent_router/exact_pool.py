"""Purpose: hard exact-signature intersection for intention-router probes.

Input: CatalogRetriever plus SessionState (hard groups from retrieve.from_slots).
Output: set[parent_asin], or None if any hard signal is missing from the index.
Role: router probe only. Soft slots are not used. None is not an empty set.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..domain import classify_constraint
from ..retrieve.from_slots import exact_pool_groups, uses_search_aliases, uses_typed_slots

if TYPE_CHECKING:
    from ..retrieve.catalog.retriever import CatalogRetriever
    from ..understand.state.session import SessionState

ConstraintSignal = str | tuple[str, str]
ConstraintGroup = tuple[str, tuple[str, ...]]


def _as_pairs(constraints: Sequence[ConstraintSignal]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in constraints:
        if isinstance(item, str):
            if item.strip():
                pairs.append((classify_constraint(item), item))
            continue
        if len(item) != 2:
            raise TypeError(f"Unsupported constraint item: {item!r}")
        attribute, value = item
        text = str(value).strip()
        if text:
            pairs.append((str(attribute), text))
    return tuple(pairs)


def _groups_from_pairs(pairs: Sequence[tuple[str, str]]) -> tuple[ConstraintGroup, ...]:
    by_attr: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for attribute, value in pairs:
        bucket = by_attr.setdefault(attribute, [])
        used = seen.setdefault(attribute, set())
        key = value.casefold()
        if not value or key in used:
            continue
        used.add(key)
        bucket.append(value)
    return tuple((attribute, tuple(values)) for attribute, values in by_attr.items() if values)


def exact_pool_for_state(
    retriever: CatalogRetriever,
    state: SessionState,
) -> set[str] | None:
    """Intersect hard signals. Soft slots are not used here."""

    groups = exact_pool_groups(state)
    category_values: tuple[str, ...] = ()
    rest: list[ConstraintGroup] = []
    for attribute, values in groups:
        if attribute == "category":
            category_values = values
        else:
            rest.append((attribute, values))
    return exact_pool_from_groups(
        retriever,
        category_values,
        rest,
        response_only=not uses_search_aliases(state) if uses_typed_slots(state) else True,
    )


def exact_pool_from_groups(
    retriever: CatalogRetriever,
    category: str | None | Sequence[str],
    groups: Sequence[ConstraintGroup],
    *,
    response_only: bool = True,
) -> set[str] | None:
    """Intersect groups. Values inside a group are a union (OR).

    A category phrase that misses the index is skipped when other hard
    groups remain (NLU category is often not a sidecar node). Category-only
    miss still returns None.
    """

    sets: list[set[str]] = []
    if isinstance(category, str):
        categories = (category,) if category.strip() else ()
    else:
        categories = tuple(item for item in (category or ()) if str(item).strip())
    if categories:
        hits: set[str] = set()
        for value in categories:
            hits.update(
                retriever.signature_candidates(
                    "category",
                    value,
                    response_only=response_only,
                )
            )
        if hits:
            sets.append(hits)
        elif not groups:
            return None
    for attribute, alternatives in groups:
        hits = set()
        for value in alternatives:
            if not str(value).strip():
                continue
            hits.update(
                retriever.signature_candidates(
                    attribute,
                    value,
                    response_only=response_only,
                )
            )
        if not hits:
            return None
        sets.append(hits)
    if not sets:
        return None
    return set.intersection(*sets)


def exact_pool(
    retriever: CatalogRetriever,
    category: str | None,
    constraints: Sequence[ConstraintSignal],
    *,
    response_only: bool = True,
) -> set[str] | None:
    """Intersect exact signals when all are known.

    Returning ``None`` means at least one signal is not represented exactly.
    Same-attribute values are one group (OR), then groups AND.
    """

    groups = _groups_from_pairs(_as_pairs(constraints))
    return exact_pool_from_groups(
        retriever, category, groups, response_only=response_only
    )
