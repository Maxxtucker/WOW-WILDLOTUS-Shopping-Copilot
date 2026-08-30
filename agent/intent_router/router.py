"""Purpose: intention router between observe and retrieve.

Input: SessionState with turn_delta, CatalogRetriever.
Output: exact parent_asin pool for retrieve; state.intention and counts written.
Role: LLM override decision, then replace or accumulate, then pool probes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..progress import emit, skip_nodes
from ..understand.state.failsafe import apply_override_failsafe
from .exact_pool import ExactPools
from .llm import (
    OverrideDecision,
    as_override_decision,
    classify_override,
    classify_route,
    has_committed_intent,
)
from .probe import pool_ratio, pool_size, probe_exact_pools
from .writeback import apply_delta, apply_override_decision

if TYPE_CHECKING:
    from ..retrieve.catalog.retriever import CatalogRetriever
    from ..understand.state.session import SessionState


_STRONG_OVERRIDE_RE = re.compile(
    r"^\s*(?:actually\s*[,;:-]?\s*)?(?:please\s+)?(?:"
    r"(?:ignore|forget|disregard)\s+(?:my|the)\s+"
    r"(?:earlier|previous|old)\s+(?:preference|request|requirement|choice)"
    r"|i(?:'ve| have)?\s+changed\s+my\s+mind"
    r"|i\s+no\s+longer\s+(?:want|need|am\s+looking\s+for)"
    r")\b",
    re.IGNORECASE,
)


def strong_override_fallback(state: SessionState) -> bool:
    """Recognize explicit start-over language when the local router misses it."""

    return bool(_STRONG_OVERRIDE_RE.search(state.latest_message or ""))


class IntentRouter:
    """Stage between observation and candidate organization."""

    def apply(
        self,
        state: SessionState,
        retriever: CatalogRetriever,
    ) -> set[str] | None:
        return route_intention(state, retriever)


def _emit_failsafe(state: SessionState) -> None:
    was_closed = not state.gate_open
    apply_override_failsafe(state, state.turn)
    applied = was_closed and state.gate_open
    emit(
        "router",
        "failsafe",
        "completed",
        {
            "input": {"turn": state.turn, "was_closed": was_closed},
            "output": {"applied": applied, "gate_open": state.gate_open},
            "why": "opens the conversion gate at turn 4 if it is still closed",
        },
    )


def _emit_route_label(intention: str) -> None:
    if intention == "buying":
        emit("router", "buying", "completed", {"intention": "buying"})
        emit("router", "browsing", "skipped", {"why": "route labeled buying"})
        return
    if intention == "browsing":
        emit("router", "browsing", "completed", {"intention": "browsing"})
        emit("router", "buying", "skipped", {"why": "route labeled browsing"})
        return
    skip_nodes("router", "buying", "browsing", why=f"route labeled {intention}")


def _commit_pools(state: SessionState, pools: ExactPools) -> set[str] | None:
    state.exact_strict = pools.strict
    state.exact_lenient = pools.lenient
    return pools.strict


def _run_override_branch(state: SessionState, retriever: CatalogRetriever):
    emit("router", "probe_override", "running")
    pools = probe_exact_pools(retriever, state)
    exact = _commit_pools(state, pools)
    emit(
        "router",
        "probe_override",
        "completed",
        {
            "exact": pool_size(exact),
            "exact_lenient": pool_size(pools.lenient),
            "output": {
                "exact": pool_size(exact),
                "exact_lenient": pool_size(pools.lenient),
            },
        },
    )
    emit(
        "router",
        "intention_override",
        "completed",
        {"intention": "override", "output": {"intention": "override"}},
    )
    skip_nodes(
        "router",
        "probe_before",
        "apply_delta",
        "probe_after",
        "route_llm",
        "buying",
        "browsing",
        why="override branch taken",
    )
    state.candidate_count_before_delta = None
    state.candidate_count = pool_size(exact)
    state.intention = "override"
    _emit_failsafe(state)
    return exact


def route_intention(
    state: SessionState,
    retriever: CatalogRetriever,
) -> set[str] | None:
    state.previous_candidate_count = state.candidate_count
    committed = has_committed_intent(state)
    decision = as_override_decision(classify_override(state))
    if decision.level == 0 and committed and strong_override_fallback(state):
        decision = OverrideDecision(2)
    if decision.level == 0 and not committed:
        skip_nodes(
            "router",
            "override_l1",
            "override_l2",
            why="no committed prior intent",
        )
    else:
        emit(
            "router",
            "override_l1",
            "completed",
            {
                "full": decision.level == 1,
                "level": decision.level,
                "output": {"full": decision.level == 1, "level": decision.level},
            },
        )
        if decision.level == 1:
            skip_nodes("router", "override_l2", why="L1 full reset")
        else:
            emit(
                "router",
                "override_l2",
                "completed",
                {
                    "override": decision.level == 2,
                    "level": decision.level,
                    "output": {
                        "override": decision.level == 2,
                        "level": decision.level,
                    },
                },
            )

    if decision.level == 1:
        emit("router", "replace_delta", "running")
        apply_override_decision(state, decision)
        emit(
            "router",
            "replace_delta",
            "completed",
            {"mode": "replace", "output": {"mode": "replace", "level": 1}},
        )
        skip_nodes("router", "drop_slots", why="L1 full reset")
        return _run_override_branch(state, retriever)

    if decision.level == 2:
        skip_nodes("router", "replace_delta", why="L2 partial override")
        emit("router", "drop_slots", "running")
        apply_override_decision(state, decision)
        emit(
            "router",
            "drop_slots",
            "completed",
            {"mode": "drop", "output": {"mode": "drop", "level": 2}},
        )
        return _run_override_branch(state, retriever)

    skip_nodes(
        "router",
        "replace_delta",
        "drop_slots",
        "probe_override",
        "intention_override",
        why="accumulate branch taken",
    )
    emit("router", "probe_before", "running")
    before_pools = probe_exact_pools(retriever, state)
    before = before_pools.strict
    emit(
        "router",
        "probe_before",
        "completed",
        {"exact": pool_size(before), "output": {"exact": pool_size(before)}},
    )
    emit("router", "apply_delta", "running")
    apply_delta(state)
    emit(
        "router",
        "apply_delta",
        "completed",
        {"mode": "accumulate", "output": {"mode": "accumulate"}},
    )
    emit("router", "probe_after", "running")
    after_pools = probe_exact_pools(retriever, state)
    after = _commit_pools(state, after_pools)
    emit(
        "router",
        "probe_after",
        "completed",
        {
            "before": pool_size(before),
            "after": pool_size(after),
            "exact": pool_size(after),
            "exact_lenient": pool_size(after_pools.lenient),
            "output": {
                "before": pool_size(before),
                "after": pool_size(after),
                "exact_lenient": pool_size(after_pools.lenient),
            },
        },
    )
    state.candidate_count_before_delta = pool_size(before)
    state.candidate_count = pool_size(after)
    ratio = pool_ratio(state.candidate_count, state.candidate_count_before_delta)
    emit("router", "route_llm", "running")
    state.intention = classify_route(
        state,
        pool_before=state.candidate_count_before_delta,
        pool_after=state.candidate_count,
        ratio=ratio,
    )
    emit(
        "router",
        "route_llm",
        "completed",
        {
            "intention": state.intention,
            "input": {
                "pool_before": state.candidate_count_before_delta,
                "pool_after": state.candidate_count,
                "ratio": None if ratio is None else round(ratio, 4),
            },
            "output": {"intention": state.intention},
        },
    )
    _emit_route_label(state.intention)
    _emit_failsafe(state)
    return after
