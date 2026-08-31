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
    "nlu_attempt",
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
    "slot_grounding",
    "repair_1",
    "repair_2",
    "repair_3",
    "disclosure",
)

UNDERSTAND_NODES = (
    "prior_miss",
    "turn_reset",
    "understand_mode",
    *UNDERSTAND_NLU_NODES,
    "regex_extract",
    "colon_restore",
    "turn_delta",
    "active_intent_evidence",
    "empty_disclosure_gate",
)

ROUTER_NODES = (
    "committed_intent",
    "override_l1",
    "override_l2",
    "strong_override_fallback",
    "replace_delta",
    "drop_slots",
    "override_gate_cleanup",
    "probe_override",
    "intention_override",
    "probe_before",
    "apply_delta",
    "probe_after",
    "pool_ratio",
    "route_llm",
    "buying",
    "browsing",
    "failsafe",
)

# Keep this list exhaustive for the normal Retrieve/Rank path. The pipeline uses
# it to mark the whole stage skipped on the empty-disclosure paging shortcut.
RETRIEVE_NODES = (
    "select_pool",
    "slot_groups",
    "rewrite_query",
    "routing",
    "lexical_in_pool",
    "score_exact",
    "hybrid_search",
    "bm25_score",
    "required_score",
    "preferred_score",
    "category_score",
    "budget_score",
    "dimension_score",
    "exclusion_score",
    "structured_subtotal",
    "rating_prior",
    "popularity_prior",
    "catalog_prior",
    "title_text_fit",
    "details_text_fit",
    "description_text_fit",
    "soft_text_fit",
    "profile_diagnostic",
    "weighted_score",
    "cap_hits",
    "raw_evidence",
    "base_only",
    "relaxed_route",
    "raw_text_route",
    "weighted_rrf",
    "qwen_rerank",
    "semantic_logits",
    "semantic_blend",
    "semantic_weights",
    "semantic_tail",
    "belief_temperature",
    "belief_hits",
    "normalize",
)

# Nodes that belong only to the joint question/slate planning path. Response
# writeback nodes are intentionally excluded because the empty-disclosure path
# still persists its paged slate and builds the official response.
DECIDE_PLAN_NODES = (
    "answer_signature",
    "eligible_questions",
    "viability_filter",
    "planning_head",
    "action_space",
    "hit_component",
    "mrr_component",
    "efficiency_component",
    "immediate_value",
    "answer_branches",
    "tail_branches",
    "future_value",
    "planner",
    "epsilon_roll",
    "technical_exploit",
    "uniform_explore",
    "selected_attribute",
    "fallback_question",
    "sequential_gate",
    "gate_rank1",
    "keep_planned",
)

DECIDE_NODES = (
    *DECIDE_PLAN_NODES,
    "persist_turn",
    "build_response",
)

STAGE_NODES = {
    "understand": UNDERSTAND_NODES,
    "router": ROUTER_NODES,
    "retrieve": RETRIEVE_NODES,
    "decide": DECIDE_NODES,
}


def progress_enabled() -> bool:
    """Return whether this context has a live diagnostic progress listener."""

    return _LISTENER.get() is not None


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
