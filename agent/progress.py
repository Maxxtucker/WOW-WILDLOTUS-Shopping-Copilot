"""Purpose: optional per-node progress events for consoles and the Chainlit circuit.

Input: a listener registered via progress_listener(); emit() calls from stages.
Output: ProgressEvent dicts. No listener means emit() is a no-op.
Role: ContextVar bus. Agent.respond and the evaluator never set a listener.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

ProgressListener = Callable[[dict[str, Any]], None]

_LISTENER: ContextVar[ProgressListener | None] = ContextVar(
    "agent_progress_listener", default=None
)

UNDERSTAND_NLU_NODES = (
    "casefold",
    "color_map",
    "material_map",
    "color_verify",
    "material_verify",
    "merge_rewrite",
    "category_l1",
    "category_l2",
    "category_l3",
    "category_cap",
    "attribute_llm",
    "repair_1",
    "repair_2",
    "repair_3",
    "disclosure",
)

ROUTER_NODES = (
    "override_l1",
    "override_l2",
    "replace_delta",
    "drop_slots",
    "probe_override",
    "intention_override",
    "probe_before",
    "apply_delta",
    "probe_after",
    "route_llm",
    "buying",
    "browsing",
    "failsafe",
)

RETRIEVE_NODES = (
    "slot_groups",
    "rewrite_query",
    "routing",
    "lexical_in_pool",
    "score_exact",
    "hybrid_search",
    "cap_hits",
    "qwen_rerank",
    "belief_hits",
    "normalize",
)

DECIDE_PLAN_NODES = (
    "answer_signature",
    "eligible_questions",
    "planner",
    "sequential_gate",
    "gate_rank1",
    "keep_planned",
)


def emit(
    stage: str,
    node: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Notify the current listener. No-op when nobody is listening."""

    listener = _LISTENER.get()
    if listener is None:
        return
    event: dict[str, Any] = {"stage": stage, "node": node, "status": status}
    if detail:
        event["detail"] = detail
    listener(event)


def skip_nodes(stage: str, *nodes: str, why: str | None = None) -> None:
    """Mark leftover graph nodes skipped. No-op without a listener."""

    if _LISTENER.get() is None:
        return
    detail = {"why": why} if why else None
    for node in nodes:
        emit(stage, node, "skipped", detail)


@contextmanager
def progress_listener(listener: ProgressListener) -> Iterator[None]:
    """Bind ``listener`` for the current context (and copied worker threads)."""

    token = _LISTENER.set(listener)
    try:
        yield
    finally:
        _LISTENER.reset(token)
