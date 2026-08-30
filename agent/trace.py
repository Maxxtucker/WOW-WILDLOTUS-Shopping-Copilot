"""Purpose: read-only per-turn stage summaries for consoles and smoke tests.

Input: SessionState plus each stage's already-computed outputs.
Output: TurnTrace with compact dicts. No extra retrieval or planning.
Role: TurnPipeline.run_traced fills this; Agent.respond discards it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .intent_router.probe import pool_ratio
from .retrieve.from_slots import exact_pool_groups

if TYPE_CHECKING:
    from .decide.clarification.types import Plan
    from .decide.ranking.normalize import RankedCandidate
    from .retrieve.catalog.types import SearchHit
    from .understand.state.session import SessionState

TRACE_TOP = 10


@dataclass(frozen=True, slots=True)
class TurnTrace:
    understand: dict[str, Any]
    router: dict[str, Any]
    retrieve: dict[str, Any]
    ranking: dict[str, Any]
    decide: dict[str, Any]
    response: dict[str, Any]
    exact: set[str] | None = None


def _slot_rows(slots: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not slots:
        return rows
    for slot in slots:
        if hasattr(slot, "as_dict"):
            rows.append(slot.as_dict())
        elif isinstance(slot, dict):
            rows.append(dict(slot))
    return rows


def _hard_groups(state: SessionState) -> list[dict[str, Any]]:
    return [
        {"attribute": attribute, "values": list(values)}
        for attribute, values in exact_pool_groups(state)
    ]


def build_understand_trace(state: SessionState) -> dict[str, Any]:
    delta = state.turn_delta
    return {
        "source": None if delta is None else delta.source,
        "category": None if delta is None else delta.category,
        "slots": _slot_rows(None if delta is None else delta.slots),
        "empty": True if delta is None else delta.empty,
        "disclosure_empty": state.disclosure_empty,
        "gate_open": state.gate_open,
        "session_category": state.category,
    }


def build_router_trace(
    state: SessionState, exact: set[str] | None
) -> dict[str, Any]:
    overridden = state.intention == "override"
    before = None if overridden else state.candidate_count_before_delta
    after = state.candidate_count
    ratio = None if overridden else pool_ratio(after, before)
    lenient = state.exact_lenient
    return {
        "intention": state.intention,
        "override": overridden,
        "route_llm": "skipped" if overridden else state.intention,
        "pool_before": before,
        "pool_after": after,
        "ratio": None if ratio is None else round(ratio, 4),
        "exact": None if exact is None else len(exact),
        "exact_sample": None if exact is None else sorted(exact)[:TRACE_TOP],
        "exact_lenient": None if lenient is None else len(lenient),
        "exact_lenient_sample": (
            None if lenient is None else sorted(lenient)[:TRACE_TOP]
        ),
        "hard_groups": _hard_groups(state),
    }


def build_retrieve_trace(
    hits: list[SearchHit],
    exact: set[str] | None,
    exact_lenient: set[str] | None = None,
) -> dict[str, Any]:
    top: list[dict[str, Any]] = []
    for hit in hits[:TRACE_TOP]:
        routes = [
            reason.removeprefix("route:").split("+")
            for reason in hit.reasons
            if reason.startswith("route:")
        ]
        top.append(
            {
                "parent_asin": hit.parent_asin,
                "score": round(float(hit.score), 4),
                "matched_constraints": list(hit.matched_constraints),
                "routes": routes[0] if routes else [],
            }
        )
    return {
        "hit_count": len(hits),
        "top": top,
        "scored_exact": bool(exact),
        "exact_lenient": None if exact_lenient is None else len(exact_lenient),
    }


def build_ranking_trace(ranked: list[RankedCandidate]) -> dict[str, Any]:
    return {
        "count": len(ranked),
        "top": [
            {
                "parent_asin": item.parent_asin,
                "probability": round(float(item.probability), 4),
            }
            for item in ranked[:TRACE_TOP]
        ],
    }


def build_decide_trace(plan: Plan, slate: list[str]) -> dict[str, Any]:
    planned = list(plan.recommendations)
    return {
        "ask_attribute": plan.ask_attribute,
        "reason": plan.reason,
        "planned_slate": planned,
        "slate": list(slate),
        "gated": planned != list(slate),
    }
