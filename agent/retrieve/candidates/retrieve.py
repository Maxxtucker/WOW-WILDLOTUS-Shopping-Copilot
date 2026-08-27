"""Purpose: organize possible products: exact pool first, else BM25 fusion.

Input: CatalogRetriever, SessionState, optional exact set.
Output: at most 500 SearchHit values.
Role: pipeline stage 5. If the scored exact pool is empty, fall back to lexical search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..filtering.exact_pool import exact_pool
from .query import rewrite_query

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
    constraints = state.ranking_constraints
    if exact is None:
        exact = exact_pool(retriever, state.category, constraints)
    if exact:
        hits = retriever.score_candidates(
            exact,
            required=constraints,
            categories=(() if state.category is None else (state.category,)),
            exclude_asins=state.excluded_asins,
        )
        if hits:
            return hits[:500]

    # Robust fallback: query rewrite contains only the current intent's
    # active evidence.  Sparse prices and store/brand are kept soft.
    query, profile_tags = rewrite_query(state, constraints)
    return retriever.search(
        query,
        required=constraints,
        preferred=profile_tags[:2],
        categories=(() if state.category is None else (state.category,)),
        exclude_asins=state.excluded_asins,
        limit=500,
        candidate_limit=1_500,
        hard_required=False,
    )
