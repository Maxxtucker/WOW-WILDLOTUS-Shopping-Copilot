"""Purpose: exact signature intersection; hard-prune candidate ASINs.

Input: CatalogRetriever plus SessionState (category and retrieve-facing groups).
Output: set[parent_asin]; None if any signal has no exact hit in the index (drop the exact path).
Role: Buying main path. Empty intersection can kill the target, so missing signals must fall back to BM25.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...domain import classify_constraint
from ..from_slots import exact_pool_groups, uses_typed_slots

if TYPE_CHECKING:
    from ..catalog.retriever import CatalogRetriever
    from ...understand.state.session import SessionState

ConstraintSignal = str | tuple[str, str]
ConstraintGroup = tuple[str, tuple[str, ...]]


class ProductFilter:
    """Stage 4: intersect exact signals, or give up."""

    def __init__(self, retriever: CatalogRetriever) -> None:
        self.retriever = retriever

    def apply(self, state: SessionState) -> set[str] | None:
        return exact_pool_for_state(self.retriever, state)


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


def exact_pool_for_state(
    retriever: CatalogRetriever,
    state: SessionState,
) -> set[str] | None:
    """Use slot groups when typed_constraints exist; else string signatures."""

    return exact_pool_from_groups(
        retriever,
        state.category,
        exact_pool_groups(state),
        response_only=not uses_typed_slots(state),
    )


def exact_pool_from_groups(
    retriever: CatalogRetriever,
    category: str | None,
    groups: Sequence[ConstraintGroup],
    *,
    response_only: bool = True,
) -> set[str] | None:
    """Intersect groups. Values inside a group are a union (OR)."""

    sets: list[set[str]] = []
    if category:
        values = set(retriever.signature_candidates("category", category))
        if not values:
            return None
        sets.append(values)
    for attribute, alternatives in groups:
        hits: set[str] = set()
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

    Returning ``None`` means at least one signal is not represented exactly,
    so the caller should use the robust lexical path instead of over-pruning.

    ``response_only=True`` is the official regex path (simulator disclose
    strings). Typed NLU uses broader search aliases.
    """

    pairs = _as_pairs(constraints)
    groups = tuple((attribute, (value,)) for attribute, value in pairs)
    return exact_pool_from_groups(
        retriever, category, groups, response_only=response_only
    )
