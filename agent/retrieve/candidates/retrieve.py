"""Purpose: score the router's exact pool, or BM25 when that pool is unavailable.

Input: CatalogRetriever, SessionState, optional exact ASIN set from the router.
Output: truncated SearchHit values (150 Buying / 500 Browsing).
Role: pipeline stage 5. Does not recompute the hard intersection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..from_slots import (
    exact_pool_groups,
    preferred_pairs,
    required_and_budget,
    uses_typed_slots,
)
from .query import rewrite_query
from .routing import routing_for

if TYPE_CHECKING:
    from ..catalog.retriever import CatalogRetriever
    from ..catalog.types import SearchHit
    from ...understand.state.session import SessionState


class CandidateOrganizer:
    """Stage 5: score the router pool, else lexical fallback."""

    def __init__(self, retriever: CatalogRetriever) -> None:
        self.retriever = retriever

    def apply(
        self,
        state: SessionState,
        exact: set[str] | None = None,
    ) -> list[SearchHit]:
        return retrieve_candidates(self.retriever, state, exact)


def _hard_categories(state: SessionState) -> tuple[str, ...]:
    for attribute, values in exact_pool_groups(state):
        if attribute == "category":
            return values
    if not uses_typed_slots(state) and state.category:
        return (state.category,)
    return ()


def _preferred(state: SessionState, profile_tags: list) -> list:
    return [*preferred_pairs(state), *profile_tags[:2]]


def retrieve_candidates(
    retriever: CatalogRetriever,
    state: SessionState,
    exact: set[str] | None = None,
) -> list[SearchHit]:
    groups, budget = required_and_budget(state)
    routing = routing_for(state.intention)
    categories = _hard_categories(state)
    if exact is not None:
        _, profile_tags = rewrite_query(state)
        hits = retriever.score_candidates(
            exact,
            required_groups=groups,
            preferred=_preferred(state, profile_tags),
            categories=categories,
            budget=budget,
            exclude_asins=state.excluded_asins,
            weights=routing.weights,
        )
        return hits[: routing.limit]

    query, profile_tags = rewrite_query(state)
    return retriever.search(
        query,
        required_groups=groups,
        preferred=_preferred(state, profile_tags),
        categories=categories,
        budget=budget,
        exclude_asins=state.excluded_asins,
        limit=routing.limit,
        candidate_limit=routing.candidate_limit,
        weights=routing.weights,
        hard_required=False,
    )
