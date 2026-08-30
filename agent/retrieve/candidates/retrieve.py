"""Purpose: score the router's exact pool, then fill with hybrid if under the floor.

Input: CatalogRetriever, SessionState, optional exact ASIN set from the router.
Output: SearchHit values (library at least 300 when exact is under 150; browsing 500).
Role: pipeline stage 5. Does not recompute the hard intersection. Hard hits
stay in front; hybrid fill (hard_required=False) pads a small exact pool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...progress import emit, skip_nodes
from ..catalog.types import DimensionSpec, SearchWeights
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
from .routing import CANDIDATE_FLOOR, library_limit_for, routing_for
from .multi_route import (
    RAW_TEXT_WEIGHT,
    RELAXED_WEIGHT,
    STRICT_WEIGHT,
    fuse_routes,
)

if TYPE_CHECKING:
    from ..catalog.retriever import CatalogRetriever
    from ..catalog.types import SearchHit
    from ...understand.state.session import SessionState


class CandidateOrganizer:
    """Stage 5: score the router pool; hybrid-fill to 300 when under 150 exact."""

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


RAW_RECALL_WEIGHTS = SearchWeights(
    lexical=2.2,
    required=0.0,
    preferred=0.0,
    category=0.0,
    budget=0.0,
    rating=0.03,
    popularity=0.05,
    missing_required=0.0,
    excluded=-8.0,
    dimension=0.0,
    text=0.0,
    profile=0.0,
)


def _safe_route_fusion(
    retriever: CatalogRetriever,
    state: SessionState,
    base_hits: list[SearchHit],
    *,
    query: str,
    groups: object,
    soft_groups: object,
    candidate_limit: int,
) -> list[SearchHit]:
    """Add relaxed and raw-text recall when live utterance evidence exists."""

    raw_text = state.current_intent_text.strip()
    if not raw_text:
        return base_hits
    limit = library_limit_for(state.intention)
    # Before the latest possible override turn has passed, another Agent call
    # does not prove that every displayed ASIN was a scored miss. Keep strict
    # precision, but let independent safety routes recover such candidates.
    safety_exclusions = (
        state.excluded_asins
        if state.override_seen or state.turn >= 5
        else ()
    )
    relaxed = retriever.search(
        query,
        required_groups=groups,
        preferred_groups=soft_groups,
        categories=(),
        budget=None,
        exclude_asins=safety_exclusions,
        limit=limit,
        candidate_limit=candidate_limit,
        weights=routing_for(state.intention).weights,
        hard_required=False,
        hard_budget=False,
        dimensions=None,
        hard_dimension=False,
        text_query=" ".join(soft_text_terms(state)),
        profile_tags=state.preference_tags,
    )
    raw = retriever.search(
        raw_text,
        required_groups=(),
        preferred_groups=(),
        categories=(),
        budget=None,
        exclude_asins=safety_exclusions,
        limit=limit,
        candidate_limit=max(candidate_limit, 2_000),
        weights=RAW_RECALL_WEIGHTS,
        hard_required=False,
        hard_budget=False,
        dimensions=None,
        hard_dimension=False,
        text_query="",
        profile_tags=(),
    )
    return fuse_routes(
        (
            ("strict", STRICT_WEIGHT, base_hits),
            ("relaxed", RELAXED_WEIGHT, relaxed),
            ("raw", RAW_TEXT_WEIGHT, raw),
        ),
        limit=limit,
    )


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
                "library_limit": library_limit_for(state.intention),
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
        exact_hits = retriever.score_candidates(
            exact,
            lexical_scores=in_pool,
            in_exact_pool=True,
            **score_kwargs,
        )
        emit(
            "retrieve",
            "score_exact",
            "completed",
            {"output": {"scored": len(exact_hits)}},
        )
        if len(exact_hits) >= CANDIDATE_FLOOR:
            skip_nodes(
                "retrieve",
                "hybrid_search",
                why="exact pool already meets candidate floor",
            )
            capped = exact_hits[: routing.limit]
            emit(
                "retrieve",
                "cap_hits",
                "completed",
                {
                    "input": {
                        "scored": len(exact_hits),
                        "limit": routing.limit,
                    },
                    "output": {
                        "hit_count": len(capped),
                        "path": "exact",
                        "exact_n": len(capped),
                        "fill_n": 0,
                    },
                    "hit_count": len(capped),
                },
            )
            return _safe_route_fusion(
                retriever,
                state,
                capped,
                query=query,
                groups=groups,
                soft_groups=soft_groups,
                candidate_limit=routing.candidate_limit,
            )
        library_limit = library_limit_for(state.intention)
        need = max(0, library_limit - len(exact_hits))
        fill_exclude = set(state.excluded_asins) | set(exact)
        emit("retrieve", "hybrid_search", "running")
        fill = retriever.search(
            query,
            limit=need,
            candidate_limit=routing.candidate_limit,
            hard_required=False,
            **{**score_kwargs, "exclude_asins": fill_exclude},
        )
        emit(
            "retrieve",
            "hybrid_search",
            "completed",
            {
                "input": {
                    "query": query[:120],
                    "limit": need,
                    "hard_required": False,
                },
                "output": {"hit_count": len(fill)},
            },
        )
        combined = exact_hits + fill
        emit(
            "retrieve",
            "cap_hits",
            "completed",
            {
                "input": {
                    "scored": len(exact_hits),
                    "limit": library_limit,
                },
                "output": {
                    "hit_count": len(combined),
                    "path": "exact+fill",
                    "exact_n": len(exact_hits),
                    "fill_n": len(fill),
                },
                "hit_count": len(combined),
            },
        )
        return _safe_route_fusion(
            retriever,
            state,
            combined,
            query=query,
            groups=groups,
            soft_groups=soft_groups,
            candidate_limit=routing.candidate_limit,
        )

    # None means no reliable exact signal; an empty set means the strict
    # intersection over-pruned. Both need lexical recovery rather than an
    # empty recommendation slate.
    skip_nodes(
        "retrieve",
        "lexical_in_pool",
        "score_exact",
        why="exact pool is empty or missing",
    )
    library_limit = library_limit_for(state.intention)
    emit("retrieve", "hybrid_search", "running")
    hits = retriever.search(
        query,
        limit=library_limit,
        candidate_limit=routing.candidate_limit,
        hard_required=False,
        **score_kwargs,
    )
    emit(
        "retrieve",
        "hybrid_search",
        "completed",
        {
            "input": {"query": query[:120], "limit": library_limit},
            "output": {"hit_count": len(hits)},
        },
    )
    emit(
        "retrieve",
        "cap_hits",
        "completed",
        {
            "input": {"limit": library_limit},
            "output": {"hit_count": len(hits), "path": "hybrid"},
            "hit_count": len(hits),
        },
    )
    return _safe_route_fusion(
        retriever,
        state,
        hits,
        query=query,
        groups=groups,
        soft_groups=soft_groups,
        candidate_limit=routing.candidate_limit,
    )
