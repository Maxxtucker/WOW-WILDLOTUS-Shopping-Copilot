"""Purpose: exact signature intersection; hard-prune candidate ASINs.

Input: CatalogRetriever, category, ranking_constraints.
Output: set[parent_asin]; None if any signal has no exact hit in the index (drop the exact path).
Role: Buying main path. Empty intersection can kill the target, so missing signals must fall back to BM25.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain import classify_constraint

if TYPE_CHECKING:
    from ..catalog.retriever import CatalogRetriever
    from ...understand.state.session import SessionState


class ProductFilter:
    """Stage 4: intersect evaluator-compatible exact signals, or give up."""

    def __init__(self, retriever: CatalogRetriever) -> None:
        self.retriever = retriever

    def apply(self, state: SessionState) -> set[str] | None:
        return exact_pool(self.retriever, state.category, state.ranking_constraints)


def exact_pool(
    retriever: CatalogRetriever,
    category: str | None,
    constraints: tuple[str, ...],
) -> set[str] | None:
    """Intersect exact, evaluator-compatible signals when all are known.

    Returning ``None`` means at least one signal is not represented exactly,
    so the caller should use the robust lexical path instead of over-pruning.
    """

    sets: list[set[str]] = []
    if category:
        values = set(retriever.signature_candidates("category", category))
        if not values:
            return None
        sets.append(values)
    for constraint in constraints:
        attribute = classify_constraint(constraint)
        values = set(
            retriever.signature_candidates(
                attribute,
                constraint,
                response_only=True,
            )
        )
        if not values:
            return None
        sets.append(values)
    if not sets:
        return None
    return set.intersection(*sets)
