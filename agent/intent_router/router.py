"""Purpose: intention router between observe and retrieve.

Input: SessionState with turn_delta, CatalogRetriever.
Output: exact parent_asin pool for retrieve; state.intention and counts written.
Role: LLM override decision, then replace or accumulate, then pool probes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..understand.state.failsafe import apply_override_failsafe
from .llm import classify_override, classify_route
from .probe import pool_ratio, pool_size, probe_exact_pool
from .writeback import apply_delta, replace_with_delta

if TYPE_CHECKING:
    from ..retrieve.catalog.retriever import CatalogRetriever
    from ..understand.state.session import SessionState


class IntentRouter:
    """Stage between observation and candidate organization."""

    def apply(
        self,
        state: SessionState,
        retriever: CatalogRetriever,
    ) -> set[str] | None:
        return route_intention(state, retriever)


def route_intention(
    state: SessionState,
    retriever: CatalogRetriever,
) -> set[str] | None:
    state.previous_candidate_count = state.candidate_count
    if classify_override(state):
        replace_with_delta(state)
        exact = probe_exact_pool(retriever, state)
        state.candidate_count_before_delta = None
        state.candidate_count = pool_size(exact)
        state.intention = "override"
        apply_override_failsafe(state, state.turn)
        return exact

    before = probe_exact_pool(retriever, state)
    state.candidate_count_before_delta = pool_size(before)
    apply_delta(state)
    after = probe_exact_pool(retriever, state)
    state.candidate_count = pool_size(after)
    ratio = pool_ratio(state.candidate_count, state.candidate_count_before_delta)
    state.intention = classify_route(
        state,
        pool_before=state.candidate_count_before_delta,
        pool_after=state.candidate_count,
        ratio=ratio,
    )
    apply_override_failsafe(state, state.turn)
    return after
