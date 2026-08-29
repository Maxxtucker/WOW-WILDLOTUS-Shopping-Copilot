"""Purpose: score the router's exact pool, or BM25 when that pool is unavailable.

Input: CatalogRetriever, SessionState, optional exact ASIN set from the router.
Output: truncated SearchHit values (150 Buying / 500 Browsing).
Role: pipeline stage 5. Does not recompute the hard intersection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..catalog.types import DimensionSpec
from ..from_slots import (
    exact_pool_groups,
    preferred_groups,
    required_and_budget,
    session_budget,
    session_dimension,
    soft_text_terms,
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


def retrieve_candidates(
    retriever: CatalogRetriever,
    state: SessionState,
    exact: set[str] | None = None,
) -> list[SearchHit]:
    groups, budget = required_and_budget(state)
    routing = routing_for(state.intention)
    categories = _hard_categories(state)
    query, _profile_tags = rewrite_query(state)
    soft_groups = preferred_groups(state)
    text_query = " ".join(soft_text_terms(state))
    hard_budget = session_budget(state, hard_only=True) is not None
    dim = session_dimension(state)
    dim_spec = (
        DimensionSpec(
            length=dim.length,
            width=dim.width,
            height=dim.height,
            weight=dim.weight,
            op=dim.op,
        )
        if dim is not None
        else None
    )
    hard_dimension = bool(dim is not None and dim.is_hard)
    score_kwargs = {
        "required_groups": groups,
        "preferred_groups": soft_groups,
        "categories": categories,
        "budget": budget,
        "exclude_asins": state.excluded_asins,
        "weights": routing.weights,
        "hard_budget": hard_budget,
        "dimensions": dim_spec,
        "hard_dimension": hard_dimension,
        "text_query": text_query,
        "profile_tags": state.preference_tags,
    }
    if exact:
        lexical = retriever.lexical_scores(query, routing.candidate_limit)
        hits = retriever.score_candidates(
            exact,
            lexical_scores={
                parent_asin: score
                for parent_asin, score in lexical.items()
                if parent_asin in exact
            },
            in_exact_pool=True,
            **score_kwargs,
        )
        return hits[: routing.limit]

    # None means no reliable exact signal; an empty set means the strict
    # intersection over-pruned. Both need lexical recovery rather than an
    # empty recommendation slate.
    return retriever.search(
        query,
        limit=routing.limit,
        candidate_limit=routing.candidate_limit,
        hard_required=False,
        **score_kwargs,
    )
