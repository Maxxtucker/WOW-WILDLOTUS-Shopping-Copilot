"""Purpose: organize possible products: exact pool first on Buying, BM25 union on Browsing.

Input: CatalogRetriever, SessionState, optional exact set.
Output: truncated SearchHit values (150 Buying / 500 Browsing).
Role: pipeline stage 5. Track routing changes weights and truncation, not the index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..filtering.exact_pool import exact_pool_for_state
from ..from_slots import required_and_budget
from .query import rewrite_query
from .routing import routing_for

if TYPE_CHECKING:
    from ..catalog.retriever import CatalogRetriever
    from ..catalog.types import SearchHit
    from ...understand.state.session import SessionState


class CandidateOrganizer:
    """Stage 5: fuse exact-signature hits with the lexical fallback."""

    def __init__(self, retriever: CatalogRetriever) -> None:
        self.retriever = retriever

    def apply(
        self,
        state: SessionState,
        exact: set[str] | None = None,
    ) -> list[SearchHit]:
        return retrieve_candidates(self.retriever, state, exact)


def retrieve_candidates(
    retriever: CatalogRetriever,
    state: SessionState,
    exact: set[str] | None = None,
) -> list[SearchHit]:
    groups, budget = required_and_budget(state)
    routing = routing_for(state.track)
    if routing.exact_first:
        if exact is None:
            exact = exact_pool_for_state(retriever, state)
        if exact:
            hits = retriever.score_candidates(
                exact,
                required_groups=groups,
                categories=(() if state.category is None else (state.category,)),
                budget=budget,
                exclude_asins=state.excluded_asins,
                weights=routing.weights,
            )
            if hits:
                return hits[: routing.limit]

    # Robust fallback (and the Browsing main path): query rewrite contains only
    # the current intent's active evidence. Sparse prices and store/brand stay soft.
    query, profile_tags = rewrite_query(state)
    return retriever.search(
        query,
        required_groups=groups,
        preferred=profile_tags[:2],
        categories=(() if state.category is None else (state.category,)),
        budget=budget,
        exclude_asins=state.excluded_asins,
        limit=routing.limit,
        candidate_limit=routing.candidate_limit,
        weights=routing.weights,
        hard_required=False,
    )
