"""Purpose: score the router's exact pool, or BM25 when that pool is unavailable.

Input: CatalogRetriever, SessionState, optional exact ASIN set from the router.
Output: truncated SearchHit values (150 Buying / 500 Browsing).
Role: pipeline stage 5. Does not recompute the hard intersection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...progress import emit, skip_nodes
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


def _group_rows(groups: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in groups or ():
        attribute, values = item
        rows.append({"attribute": str(attribute), "values": list(values)})
    return rows


def retrieve_candidates(
    retriever: CatalogRetriever,
    state: SessionState,
    exact: set[str] | None = None,
) -> list[SearchHit]:
    emit("retrieve", "slot_groups", "running")
    groups, budget = required_and_budget(state)
    soft_groups = preferred_groups(state)
    emit(
        "retrieve",
        "slot_groups",
        "completed",
        {
            "input": {"intention": state.intention},
            "output": {
                "required": _group_rows(groups),
                "preferred": _group_rows(soft_groups),
                "budget": None if budget is None else {"low": budget[0], "high": budget[1]},
            },
        },
    )
    emit("retrieve", "rewrite_query", "running")
    routing = routing_for(state.intention)
    categories = _hard_categories(state)
    query, _profile_tags = rewrite_query(state)
    emit(
        "retrieve",
        "rewrite_query",
        "completed",
        {
            "input": {"category": state.category},
            "output": {"query": query[:160]},
        },
    )
    emit("retrieve", "routing", "running")
    emit(
        "retrieve",
        "routing",
        "completed",
        {
            "input": {"intention": state.intention},
            "output": {
                "limit": routing.limit,
                "candidate_limit": routing.candidate_limit,
                "exact_first": routing.exact_first,
            },
        },
    )
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
        skip_nodes(
            "retrieve",
            "hybrid_search",
            why="exact pool is nonempty",
        )
        emit("retrieve", "lexical_in_pool", "running")
        lexical = retriever.lexical_scores(query, routing.candidate_limit)
        in_pool = {
            parent_asin: score
            for parent_asin, score in lexical.items()
            if parent_asin in exact
        }
        emit(
            "retrieve",
            "lexical_in_pool",
            "completed",
            {
                "input": {"exact": len(exact), "query": query[:120]},
                "output": {"lexical_in_pool": len(in_pool)},
            },
        )
        emit("retrieve", "score_exact", "running")
        hits = retriever.score_candidates(
            exact,
            lexical_scores=in_pool,
            in_exact_pool=True,
            **score_kwargs,
        )
        emit(
            "retrieve",
            "score_exact",
            "completed",
            {"output": {"scored": len(hits)}},
        )
        capped = hits[: routing.limit]
        emit(
            "retrieve",
            "cap_hits",
            "completed",
            {
                "input": {"scored": len(hits), "limit": routing.limit},
                "output": {"hit_count": len(capped), "path": "exact"},
                "hit_count": len(capped),
            },
        )
        return capped

    # None means no reliable exact signal; an empty set means the strict
    # intersection over-pruned. Both need lexical recovery rather than an
    # empty recommendation slate.
    skip_nodes(
        "retrieve",
        "lexical_in_pool",
        "score_exact",
        why="exact pool is empty or missing",
    )
    emit("retrieve", "hybrid_search", "running")
    hits = retriever.search(
        query,
        limit=routing.limit,
        candidate_limit=routing.candidate_limit,
        hard_required=False,
        **score_kwargs,
    )
    emit(
        "retrieve",
        "hybrid_search",
        "completed",
        {
            "input": {"query": query[:120], "limit": routing.limit},
            "output": {"hit_count": len(hits)},
        },
    )
    emit(
        "retrieve",
        "cap_hits",
        "completed",
        {
            "input": {"limit": routing.limit},
            "output": {"hit_count": len(hits), "path": "hybrid"},
            "hit_count": len(hits),
        },
    )
    return hits
