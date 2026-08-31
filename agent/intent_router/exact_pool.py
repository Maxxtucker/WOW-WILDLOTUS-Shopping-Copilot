"""Purpose: hard exact-signature intersection for intention-router probes.

Input: CatalogRetriever plus SessionState (hard groups from retrieve.from_slots).
Output: ExactPools (strict + lenient), or None sets if a hard signal is missing.
Role: router probe only. Soft slots are not used. None is not an empty set.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..domain import classify_constraint
from ..retrieve.catalog.types import DimensionSpec
from ..retrieve.from_slots import (
    exact_pool_groups,
    session_budget,
    session_dimension,
    uses_search_aliases,
    uses_typed_slots,
)

if TYPE_CHECKING:
    from ..retrieve.catalog.retriever import CatalogRetriever
    from ..understand.state.session import SessionState

ConstraintSignal = str | tuple[str, str]
ConstraintGroup = tuple[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ExactPools:
    """Strict hard intersection plus match-or-unknown lenient superset."""

    strict: set[str] | None
    lenient: set[str] | None


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


def _category_values(category: str | None | Sequence[str]) -> tuple[str, ...]:
    if isinstance(category, str):
        return (category,) if category.strip() else ()
    return tuple(item for item in (category or ()) if str(item).strip())


def _union_hits(
    retriever: CatalogRetriever,
    attribute: str,
    values: Sequence[str],
    *,
    response_only: bool,
) -> set[str]:
    hits: set[str] = set()
    for value in values:
        if not str(value).strip():
            continue
        hits.update(
            retriever.signature_candidates(
                attribute,
                value,
                response_only=response_only,
            )
        )
    return hits


def _applied_group_matches(
    retriever: CatalogRetriever,
    category: str | None | Sequence[str],
    groups: Sequence[ConstraintGroup],
    *,
    response_only: bool,
) -> tuple[list[tuple[str, set[str]]], bool]:
    """Match set per applied hard group, plus whether strict intersection is valid.

    A category miss is skipped when other groups remain. Category-only miss
    returns no groups and strict_ok False. A non-category empty match keeps
    the group for lenient unknown-union and sets strict_ok False.
    """

    applied: list[tuple[str, set[str]]] = []
    strict_ok = True
    rest = list(groups)
    categories = _category_values(category)
    if categories:
        hits = _union_hits(
            retriever, "category", categories, response_only=response_only
        )
        if hits:
            applied.append(("category", hits))
        elif not rest:
            return [], False
    for attribute, alternatives in rest:
        hits = _union_hits(
            retriever, attribute, alternatives, response_only=response_only
        )
        if not hits:
            strict_ok = False
        applied.append((attribute, hits))
    return applied, strict_ok


def _signature_pools_from_groups(
    retriever: CatalogRetriever,
    category: str | None | Sequence[str],
    groups: Sequence[ConstraintGroup],
    *,
    response_only: bool = True,
) -> ExactPools:
    applied, strict_ok = _applied_group_matches(
        retriever, category, groups, response_only=response_only
    )
    if not applied:
        return ExactPools(None, None)
    universe = retriever.all_parent_asins()
    strict_sets: list[set[str]] = []
    lenient_sets: list[set[str]] = []
    for attribute, match in applied:
        if strict_ok:
            strict_sets.append(match)
        known = retriever.asins_with_attribute(attribute, response_only=response_only)
        lenient_sets.append(match | set(universe - known))
    strict = set.intersection(*strict_sets) if strict_ok else None
    lenient = set.intersection(*lenient_sets)
    return ExactPools(strict, lenient)


def _split_state_groups(
    state: SessionState,
) -> tuple[tuple[str, ...], list[ConstraintGroup], bool]:
    groups = exact_pool_groups(state)
    category_values: tuple[str, ...] = ()
    rest: list[ConstraintGroup] = []
    for attribute, values in groups:
        if attribute == "category":
            category_values = values
        else:
            rest.append((attribute, values))
    response_only = (
        not uses_search_aliases(state) if uses_typed_slots(state) else True
    )
    return category_values, rest, response_only


def _numeric_spec(
    state: SessionState,
) -> tuple[
    tuple[float | None, float | None] | None,
    DimensionSpec | None,
    bool,
]:
    budget = session_budget(state, hard_only=True)
    dim = session_dimension(state)
    hard_dimension = bool(dim is not None and dim.is_hard and dim.stated())
    spec = (
        DimensionSpec(
            length=dim.length,
            width=dim.width,
            height=dim.height,
            weight=dim.weight,
            op=dim.op,
        )
        if hard_dimension and dim is not None
        else None
    )
    return budget, spec, hard_dimension


def exact_pools_for_state(
    retriever: CatalogRetriever,
    state: SessionState,
) -> ExactPools:
    """Strict hard intersection plus match-or-unknown lenient pool."""

    category_values, rest, response_only = _split_state_groups(state)
    pools = _signature_pools_from_groups(
        retriever,
        category_values,
        rest,
        response_only=response_only,
    )
    budget, spec, hard_dimension = _numeric_spec(state)
    strict = pools.strict
    lenient = pools.lenient
    if budget is not None or hard_dimension:
        strict = (
            None
            if strict is None
            else retriever.filter_hard_numeric(
                strict,
                budget=budget,
                dimensions=spec,
                hard_budget=budget is not None,
                hard_dimension=hard_dimension,
                allow_missing=False,
            )
        )
        lenient = (
            None
            if lenient is None
            else retriever.filter_hard_numeric(
                lenient,
                budget=budget,
                dimensions=spec,
                hard_budget=budget is not None,
                hard_dimension=hard_dimension,
                allow_missing=True,
            )
        )
    blocked = state.excluded_asins
    return ExactPools(
        None if strict is None else strict - blocked,
        None if lenient is None else lenient - blocked,
    )


def pool_probe_diagnostics(state: SessionState) -> dict[str, object]:
    """Describe exact-pool construction without recomputing candidate sets."""

    budget, _spec, hard_dimension = _numeric_spec(state)
    return {
        "within_attribute": "OR",
        "across_attributes": "AND",
        "hard_groups": [
            {"attribute": attribute, "values": list(values)}
            for attribute, values in exact_pool_groups(state)
        ],
        "lenient_unknown": (
            "match OR catalog-unknown; known mismatch is still excluded"
        ),
        "numeric": {
            "budget": None if budget is None else [budget[0], budget[1]],
            "hard_dimension": hard_dimension,
            "strict_allow_missing": False,
            "lenient_allow_missing": True,
        },
        "excluded_asins": len(state.excluded_asins),
    }


def exact_pool_for_state(
    retriever: CatalogRetriever,
    state: SessionState,
) -> set[str] | None:
    """Intersect hard signals. Soft slots are not used here."""

    return exact_pools_for_state(retriever, state).strict


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

    return _signature_pools_from_groups(
        retriever, category, groups, response_only=response_only
    ).strict


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
