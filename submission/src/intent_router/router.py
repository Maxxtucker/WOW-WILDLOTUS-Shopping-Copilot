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
from .exact_pool import ExactPools, pool_probe_diagnostics
from .llm import (
    OverrideDecision,
    as_override_decision,
    classify_override,
    classify_route,
    has_committed_intent,
)
from .probe import pool_ratio, pool_size, probe_exact_pools
from .writeback import (
    apply_delta,
    apply_override_decision,
    delta_attribute_names,
    delta_has_category,
)

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
        emit(
            "router",
            "buying",
            "completed",
            {
                "intention": "buying",
                "input": {"classified_intention": intention},
                "output": {
                    "route": "buying",
                    "retrieval_mode": "focused structured weighting",
                },
            },
        )
        emit("router", "browsing", "skipped", {"why": "route labeled buying"})
        return
    if intention == "browsing":
        emit(
            "router",
            "browsing",
            "completed",
            {
                "intention": "browsing",
                "input": {"classified_intention": intention},
                "output": {
                    "route": "browsing",
                    "retrieval_mode": "broad lexical weighting",
                },
            },
        )
        emit("router", "buying", "skipped", {"why": "route labeled browsing"})
        return
    skip_nodes("router", "buying", "browsing", why=f"route labeled {intention}")


def _commit_pools(state: SessionState, pools: ExactPools) -> set[str] | None:
    state.exact_strict = pools.strict
    state.exact_lenient = pools.lenient
    return pools.strict


def _pool_probe_input(state: SessionState) -> dict[str, object]:
    return pool_probe_diagnostics(state)


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
            "input": _pool_probe_input(state),
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
        "pool_ratio",
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
    emit(
        "router",
        "committed_intent",
        "completed",
        {
            "input": {
                "category": state.category,
                "typed_constraints": len(state.typed_constraints),
                "active_constraints": len(state.active_constraints),
                "legacy_hints": len(state.legacy_hints),
                "previous_candidate_count": state.previous_candidate_count,
            },
            "output": {
                "has_committed_intent": committed,
                "next": "classify override" if committed else "accumulate",
            },
        },
    )
    decision = as_override_decision(classify_override(state))
    fallback_applied = False
    if decision.level == 0 and committed:
        emit(
            "router",
            "strong_override_fallback",
            "running",
            {"input": {"message": state.latest_message, "llm_level": 0}},
        )
        fallback_applied = strong_override_fallback(state)
        emit(
            "router",
            "strong_override_fallback",
            "completed",
            {
                "input": {"message": state.latest_message, "llm_level": 0},
                "output": {
                    "matched": fallback_applied,
                    "level": 2 if fallback_applied else 0,
                },
            },
        )
        if fallback_applied:
            decision = OverrideDecision(2)
    else:
        skip_nodes(
            "router",
            "strong_override_fallback",
            why=(
                "there is no committed intent"
                if not committed
                else "the LLM override decision already selected a branch"
            ),
        )
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
                "input": {
                    "has_committed_intent": committed,
                    "delta_has_category": delta_has_category(state.turn_delta),
                },
                "output": {
                    "full": decision.level == 1,
                    "level": decision.level,
                    "category_guard_passed": (
                        decision.level == 1
                        and delta_has_category(state.turn_delta)
                    ),
                },
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
                    "input": {
                        "l1_accepted": False,
                        "message": state.latest_message,
                    },
                    "output": {
                        "override": decision.level == 2,
                        "level": decision.level,
                        "source": (
                            "strong explicit fallback"
                            if fallback_applied
                            else "LLM"
                        ),
                    },
                },
            )

    if decision.level == 1:
        emit("router", "replace_delta", "running")
        committed_before = {
            "category": state.category,
            "typed_constraints": len(state.typed_constraints),
            "active_constraints": len(state.active_constraints),
        }
        gate_before = {
            "intent_version": state.intent_version,
            "excluded": len(state.excluded_asins),
            "shown": len(state.shown_asins),
            "asked": len(state.asked),
        }
        apply_override_decision(state, decision)
        emit(
            "router",
            "replace_delta",
            "completed",
            {
                "mode": "replace",
                "input": committed_before,
                "output": {
                    "mode": "replace",
                    "level": 1,
                    "category": state.category,
                    "typed_constraints": len(state.typed_constraints),
                    "active_constraints": len(state.active_constraints),
                },
            },
        )
        skip_nodes("router", "drop_slots", why="L1 full reset")
        emit(
            "router",
            "override_gate_cleanup",
            "completed",
            {
                "input": gate_before,
                "output": {
                    "intent_version": state.intent_version,
                    "gate_open": state.gate_open,
                    "excluded": len(state.excluded_asins),
                    "shown": len(state.shown_asins),
                    "asked": len(state.asked),
                    "active_intent_messages": len(state.current_intent_messages),
                },
            },
        )
        return _run_override_branch(state, retriever)

    if decision.level == 2:
        skip_nodes("router", "replace_delta", why="L2 partial override")
        emit("router", "drop_slots", "running")
        replaced_attributes = sorted(delta_attribute_names(state.turn_delta))
        committed_before = {
            "category": state.category,
            "typed_constraints": len(state.typed_constraints),
            "active_constraints": len(state.active_constraints),
            "replaced_attributes": replaced_attributes,
        }
        gate_before = {
            "intent_version": state.intent_version,
            "excluded": len(state.excluded_asins),
            "shown": len(state.shown_asins),
            "asked": len(state.asked),
        }
        apply_override_decision(state, decision)
        emit(
            "router",
            "drop_slots",
            "completed",
            {
                "mode": "drop",
                "input": committed_before,
                "output": {
                    "mode": "drop",
                    "level": 2,
                    "replaced_attributes": replaced_attributes,
                    "category": state.category,
                    "typed_constraints": len(state.typed_constraints),
                    "active_constraints": len(state.active_constraints),
                },
            },
        )
        emit(
            "router",
            "override_gate_cleanup",
            "completed",
            {
                "input": gate_before,
                "output": {
                    "intent_version": state.intent_version,
                    "gate_open": state.gate_open,
                    "excluded": len(state.excluded_asins),
                    "shown": len(state.shown_asins),
                    "asked": len(state.asked),
                    "active_intent_messages": len(state.current_intent_messages),
                },
            },
        )
        return _run_override_branch(state, retriever)

    skip_nodes(
        "router",
        "replace_delta",
        "drop_slots",
        "override_gate_cleanup",
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
        {
            "exact": pool_size(before),
            "exact_lenient": pool_size(before_pools.lenient),
            "input": _pool_probe_input(state),
            "output": {
                "exact": pool_size(before),
                "exact_lenient": pool_size(before_pools.lenient),
            },
        },
    )
    emit("router", "apply_delta", "running")
    committed_before = {
        "category": state.category,
        "typed_constraints": len(state.typed_constraints),
        "active_constraints": len(state.active_constraints),
    }
    apply_delta(state)
    emit(
        "router",
        "apply_delta",
        "completed",
        {
            "mode": "accumulate",
            "input": committed_before,
            "output": {
                "mode": "accumulate",
                "category": state.category,
                "typed_constraints": len(state.typed_constraints),
                "active_constraints": len(state.active_constraints),
            },
        },
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
            "input": _pool_probe_input(state),
            "output": {
                "before": pool_size(before),
                "after": pool_size(after),
                "exact": pool_size(after),
                "exact_lenient": pool_size(after_pools.lenient),
            },
        },
    )
    state.candidate_count_before_delta = pool_size(before)
    state.candidate_count = pool_size(after)
    ratio = pool_ratio(state.candidate_count, state.candidate_count_before_delta)
    emit(
        "router",
        "pool_ratio",
        "completed",
        {
            "input": {
                "before": state.candidate_count_before_delta,
                "after": state.candidate_count,
            },
            "output": {
                "ratio": None if ratio is None else round(ratio, 4),
                "defined": ratio is not None,
            },
            "why": (
                None
                if ratio is not None
                else "ratio is undefined when either pool is unrepresentable or before is zero"
            ),
        },
    )
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
