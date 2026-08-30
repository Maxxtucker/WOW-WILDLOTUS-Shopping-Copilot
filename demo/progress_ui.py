"""Purpose: map agent progress events onto Chainlit circuit and inspector props.

Input: ProgressEvent dicts from agent.progress plus an optional TurnTrace.
Output: JSON-safe props for PipelineCircuit and NodeInspector.
Role: UI state only. Does not run the pipeline.
"""

from __future__ import annotations

import time
from typing import Any

from agent.trace import TurnTrace
from demo.node_catalog import NODE_CATALOG

NODE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("casefold", "understand", "Normalize text"),
    ("color_map", "understand", "Normalize color"),
    ("material_map", "understand", "Normalize material"),
    ("color_verify", "understand", "Validate mapped color"),
    ("material_verify", "understand", "Validate mapped material"),
    ("merge_rewrite", "understand", "Build normalized query"),
    ("category_l1", "understand", "Find broad product family"),
    ("category_l2", "understand", "Narrow to product type"),
    ("category_l3", "understand", "Resolve final category"),
    ("category_cap", "understand", "Limit category ambiguity"),
    ("attribute_llm", "understand", "Extract user constraints"),
    ("repair_1", "understand", "LLM Retry 1"),
    ("repair_2", "understand", "LLM Retry 2"),
    ("repair_3", "understand", "LLM Retry 3"),
    ("disclosure", "understand", "Disclosure"),
    ("turn_delta", "understand", "Turn delta"),
    ("override_l1", "router", "Judge Global Override"),
    ("override_l2", "router", "Judge Field Override"),
    ("replace_delta", "router", "Replace"),
    ("drop_slots", "router", "Drop slots"),
    ("probe_override", "router", "Probe once"),
    ("intention_override", "router", "Override label"),
    ("probe_before", "router", "Probe current Pool"),
    ("apply_delta", "router", "Update new constraints"),
    ("probe_after", "router", "Probe current Pool"),
    ("route_llm", "router", "LLM intent judge"),
    ("buying", "router", "Buying"),
    ("browsing", "router", "Browsing"),
    ("failsafe", "router", "Failsafe"),
    ("slot_groups", "retrieve", "Slot groups"),
    ("rewrite_query", "retrieve", "Query"),
    ("routing", "retrieve", "Routing"),
    ("lexical_in_pool", "retrieve", "Lexical ∩ pool"),
    ("score_exact", "retrieve", "Score exact"),
    ("hybrid_search", "retrieve", "Hybrid search"),
    ("cap_hits", "retrieve", "Cap hits"),
    ("qwen_rerank", "retrieve", "Qwen rerank"),
    ("belief_hits", "retrieve", "Belief"),
    ("normalize", "retrieve", "Normalize"),
    ("answer_signature", "decide", "Answers"),
    ("eligible_questions", "decide", "Questions"),
    ("planner", "decide", "Planner"),
    ("sequential_gate", "decide", "Slate gate"),
    ("gate_rank1", "decide", "Rank-1"),
    ("keep_planned", "decide", "Keep slate"),
    ("persist_turn", "decide", "Persist"),
    ("build_response", "decide", "Respond"),
)

STAGE_ORDER = ("understand", "router", "retrieve", "decide")

DONE = frozenset({"completed", "skipped", "error"})

GRAPH_FOR_STAGE = {
    "understand": "understand",
    "router": "router",
    "retrieve": "retrieve",
    "decide": "decide",
}

NEXT_GRAPH = {
    "understand": "router",
    "router": "retrieve",
    "retrieve": "decide",
}


def empty_circuit_state() -> dict[str, Any]:
    """Initial circuit props: every node pending."""

    nodes: dict[str, Any] = {}
    for node_id, stage, label in NODE_SPECS:
        extra = NODE_CATALOG.get(node_id) or {}
        nodes[node_id] = {
            "id": node_id,
            "stage": stage,
            "label": label,
            "status": "pending",
            "function": extra.get("function") or "",
            "implementation": extra.get("implementation") or extra.get("meaning") or "",
        }
    return {
        "title": "Agent pipeline",
        "status": "running",
        "current": "casefold",
        "activeGraph": "understand",
        "viewGraph": "",
        "selectedNode": "",
        "turn": 0,
        "progressPercent": 0,
        "error": "",
        "startedAt": time.time(),
        "nodes": nodes,
        "stages": {name: {"status": "pending", "summary": ""} for name in STAGE_ORDER},
    }


def empty_inspect_turn(turn: int, original: str, nodes: dict[str, Any]) -> dict[str, Any]:
    """One inspector turn row. ``nodes`` is the live circuit node map."""

    return {"turn": turn, "original": original, "nodes": nodes}


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Mutate circuit props from one progress event. Returns the same dict."""

    stage = str(event.get("stage") or "")
    node_id = str(event.get("node") or "")
    status = str(event.get("status") or "pending")
    detail = event.get("detail")
    if not isinstance(detail, dict):
        detail = {}

    if node_id == "stage" and stage in state["stages"]:
        state["stages"][stage]["status"] = status
        summary = _stage_summary(stage, detail)
        if summary:
            state["stages"][stage]["summary"] = summary
        if status == "running":
            state["current"] = stage
            _set_active_graph(state, stage)
        elif status in {"completed", "skipped"}:
            nxt = NEXT_GRAPH.get(stage)
            if nxt:
                state["activeGraph"] = nxt
        return _refresh_progress(state)

    node = state["nodes"].get(node_id)
    if node is None:
        return _refresh_progress(state)
    if status == "skipped" and node["status"] in {"completed", "error"}:
        return _refresh_progress(state)
    node["status"] = status
    if detail:
        node["detail"] = detail
        caption = _node_caption(node_id, detail)
        if caption:
            node["summary"] = caption
    if status == "running":
        state["current"] = node_id
        stage_name = node.get("stage")
        _set_active_graph(state, str(stage_name or ""))
        if stage_name in state["stages"] and state["stages"][stage_name]["status"] == "pending":
            state["stages"][stage_name]["status"] = "running"
    elif status == "error":
        state["status"] = "error"
        state["error"] = str(detail.get("error") or f"{node_id} failed")
        state["stages"][node["stage"]]["status"] = "error"
    return _refresh_progress(state)


def apply_understand_event(turn_state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Fold understand-node details into the inspector row metadata."""

    if event.get("stage") != "understand":
        return turn_state
    node_id = str(event.get("node") or "")
    detail = event.get("detail")
    if not isinstance(detail, dict):
        return turn_state
    if node_id == "merge_rewrite":
        turn_state["rewritten"] = str(detail.get("rewritten") or "")
        if detail.get("original") and not turn_state.get("original"):
            turn_state["original"] = str(detail["original"])
    elif node_id in {"turn_delta", "stage"}:
        _apply_understand_detail(turn_state, detail)
    return turn_state


def apply_understand_from_trace(turn_state: dict[str, Any], trace: TurnTrace) -> dict[str, Any]:
    """Fill leftover understand fields from the finished trace."""

    _apply_understand_detail(turn_state, trace.understand)
    return turn_state


def finalize_circuit(state: dict[str, Any], trace: TurnTrace | None) -> dict[str, Any]:
    """Mark leftover nodes skipped and attach stage summaries from the trace."""

    for node in state["nodes"].values():
        if node["status"] in {"pending", "running"}:
            node["status"] = "skipped"
            node.setdefault("detail", {})
            if "why" not in node["detail"]:
                node["detail"]["why"] = "not reached this turn"
    if trace is not None:
        state["stages"]["understand"]["summary"] = _stage_summary(
            "understand", trace.understand
        )
        state["stages"]["router"]["summary"] = _stage_summary("router", trace.router)
        state["stages"]["retrieve"]["summary"] = _stage_summary(
            "retrieve", trace.retrieve
        )
        state["stages"]["decide"]["summary"] = _stage_summary("decide", trace.decide)
        for name in STAGE_ORDER:
            if state["stages"][name]["status"] != "error":
                state["stages"][name]["status"] = "completed"
    if state["status"] != "error":
        state["status"] = "completed"
    state["progressPercent"] = 100
    state["current"] = "build_response"
    state["activeGraph"] = "decide"
    return state


def _apply_understand_detail(turn_state: dict[str, Any], detail: dict[str, Any]) -> None:
    if "source" in detail:
        turn_state["source"] = detail.get("source")
    if "empty" in detail:
        turn_state["empty"] = bool(detail["empty"])
    if "repair_rounds" in detail:
        turn_state["repair_rounds"] = int(detail["repair_rounds"] or 0)
    if "gate_open" in detail:
        turn_state["gate_open"] = detail.get("gate_open")
    if "session_category" in detail:
        turn_state["session_category"] = detail.get("session_category")


def _set_active_graph(state: dict[str, Any], stage: str) -> None:
    graph = GRAPH_FOR_STAGE.get(stage)
    if graph:
        state["activeGraph"] = graph


def _refresh_progress(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state["nodes"]
    done = sum(1 for node in nodes.values() if node["status"] in DONE)
    total = max(1, len(nodes))
    state["progressPercent"] = min(100, int(round(100 * done / total)))
    return state


def _from_io(detail: dict[str, Any], key: str, fallback: str) -> str:
    output = detail.get("output")
    if isinstance(output, dict) and output.get(key) not in (None, ""):
        return str(output[key])
    if detail.get(key) not in (None, ""):
        return str(detail[key])
    return fallback


def _node_caption(node_id: str, detail: dict[str, Any]) -> str:
    if node_id == "merge_rewrite":
        rewritten = str(detail.get("rewritten") or "").strip()
        if rewritten:
            return rewritten[:72]
    if node_id in {"color_map", "material_map", "color_verify", "material_verify"}:
        hits = detail.get("hits") or []
        return f"{len(hits)} hit" + ("" if len(hits) == 1 else "s")
    if node_id.startswith("category_l"):
        labels = detail.get("labels") or []
        return ", ".join(str(item) for item in labels) if labels else "none"
    if node_id == "category_cap":
        kept = detail.get("kept") or []
        if kept:
            return ", ".join(str(item) for item in kept)
    if node_id == "disclosure":
        flag = detail.get("empty")
        if flag is True:
            return "empty"
        if flag is False:
            return "disclosed"
    if node_id == "override_l1":
        flag = detail.get("full")
        if isinstance(detail.get("output"), dict):
            flag = detail["output"].get("full", flag)
        if flag is None:
            return ""
        return "full reset" if flag else "not full"
    if node_id == "override_l2":
        flag = detail.get("override")
        if isinstance(detail.get("output"), dict):
            flag = detail["output"].get("override", flag)
        if flag is None:
            return ""
        return "replace fields" if flag else "accumulate"
    if node_id in {"probe_override", "probe_before", "probe_after"}:
        exact = detail.get("exact")
        if exact is None and isinstance(detail.get("output"), dict):
            exact = detail["output"].get("exact")
        return "hybrid" if exact is None else f"exact={exact}"
    if node_id == "route_llm":
        return _from_io(detail, "intention", "")
    if node_id in {"buying", "browsing", "intention_override"}:
        return _from_io(detail, "intention", "")
    if node_id == "cap_hits":
        count = detail.get("hit_count")
        if count is None and isinstance(detail.get("output"), dict):
            count = detail["output"].get("hit_count")
        return "" if count is None else f"{count} hits"
    if node_id == "normalize":
        count = detail.get("count")
        if count is None and isinstance(detail.get("output"), dict):
            count = detail["output"].get("count")
        return "" if count is None else f"{count} ranked"
    if node_id == "planner":
        return str(detail.get("ask_attribute") or _from_io(detail, "reason", ""))
    if node_id == "turn_delta":
        source = detail.get("source")
        return "" if source is None else f"source={source}"
    why = detail.get("why")
    if why:
        return str(why)[:72]
    return ""


def _stage_summary(stage: str, detail: dict[str, Any]) -> str:
    if stage == "understand":
        source = detail.get("source") or "-"
        category = detail.get("category") or "-"
        gate = "open" if detail.get("gate_open") else "closed"
        return f"source={source}\ncategory={category}\ngate={gate}"
    if stage == "router":
        intention = detail.get("intention") or "-"
        exact = detail.get("exact")
        exact_bit = "None" if exact is None else str(exact)
        return f"intention={intention}\nexact={exact_bit}"
    if stage == "retrieve":
        count = detail.get("hit_count")
        top = detail.get("top") or []
        head = top[0] if top else None
        extra = ""
        if isinstance(head, dict) and head.get("parent_asin"):
            extra = f"\ntop {head['parent_asin']}"
        return f"{count or 0} hits{extra}"
    if stage == "decide":
        ask = detail.get("ask_attribute") or "-"
        slate = detail.get("slate")
        planned = detail.get("planned_slate")
        slate_n = len(slate) if isinstance(slate, list) else slate
        planned_n = len(planned) if isinstance(planned, list) else planned
        return f"ask={ask}\nslate={slate_n or 0}\nplanned={planned_n or 0}"
    return ""
