"""Purpose: map agent progress events onto Chainlit circuit and inspector props.

Input: ProgressEvent dicts from agent.progress plus an optional TurnTrace.
Output: JSON-safe props for PipelineCircuit and NodeInspector.
Role: UI state only. Does not run or alter the recommendation pipeline.
"""

from __future__ import annotations

import time
from typing import Any

from agent.trace import TurnTrace
# Importing the extension mutates the legacy catalog dictionaries in place, so
# chainlit_app's already-imported NODE_CATALOG/STAGE_BLURBS references also see
# the README-aligned descriptions.
from demo.node_catalog_ext import NODE_CATALOG

NODE_SPECS: tuple[tuple[str, str, str], ...] = (
    # Understand
    ("casefold", "understand", "Normalize text"),
    ("color_map", "understand", "Map color aliases"),
    ("material_map", "understand", "Map material aliases"),
    ("color_verify", "understand", "Verify color words"),
    ("material_verify", "understand", "Verify material words"),
    ("merge_rewrite", "understand", "Build normalized query"),
    ("category_l1", "understand", "Category · L1 roots"),
    ("category_l2", "understand", "Category · L2 children"),
    ("category_l3", "understand", "Category · L3 children"),
    ("category_cap", "understand", "Cap category ambiguity"),
    ("attribute_llm", "understand", "Extract typed constraints"),
    ("repair_1", "understand", "Grounding repair · 1"),
    ("repair_2", "understand", "Grounding repair · 2"),
    ("repair_3", "understand", "Grounding repair · 3"),
    ("disclosure", "understand", "Validate disclosure"),
    ("turn_delta", "understand", "Stage turn delta"),
    # Intent router
    ("override_l1", "router", "L1 full override?"),
    ("override_l2", "router", "L2 field override?"),
    ("replace_delta", "router", "Replace committed intent"),
    ("drop_slots", "router", "Drop replaced fields"),
    ("probe_override", "router", "Probe replacement pool"),
    ("intention_override", "router", "Route as override"),
    ("probe_before", "router", "Probe exact pool · before"),
    ("apply_delta", "router", "Commit turn delta"),
    ("probe_after", "router", "Probe exact pool · after"),
    ("route_llm", "router", "Classify Buying / Browsing"),
    ("buying", "router", "Buying route"),
    ("browsing", "router", "Browsing route"),
    ("failsafe", "router", "Turn-4 gate failsafe"),
    # Retrieve + rank
    ("select_pool", "retrieve", "Select strict / lenient pool"),
    ("slot_groups", "retrieve", "Build scoring groups"),
    ("rewrite_query", "retrieve", "Build lexical query"),
    ("routing", "retrieve", "Load route weights / limits"),
    ("lexical_in_pool", "retrieve", "BM25 inside selected pool"),
    ("score_exact", "retrieve", "Score selected pool"),
    ("hybrid_search", "retrieve", "Hybrid base recall / fill"),
    ("cap_hits", "retrieve", "Assemble base library"),
    ("raw_evidence", "retrieve", "Check active-intent raw evidence"),
    ("base_only", "retrieve", "Use base route only"),
    ("relaxed_route", "retrieve", "Safety recall · relaxed"),
    ("raw_text_route", "retrieve", "Safety recall · raw text"),
    ("weighted_rrf", "retrieve", "Fuse routes · weighted RRF"),
    ("qwen_rerank", "retrieve", "Semantic head rerank"),
    ("belief_hits", "retrieve", "Deterministic score belief"),
    ("normalize", "retrieve", "Normalize ranking mass"),
    # Decide
    ("answer_signature", "decide", "Cache predicted answers"),
    ("eligible_questions", "decide", "Generate eligible questions"),
    ("viability_filter", "decide", "Filter question viability"),
    ("planning_head", "decide", "Build planning head + tail"),
    ("action_space", "decide", "Enumerate question × slate size"),
    ("planner", "decide", "Dynamic slate planner"),
    ("fallback_question", "decide", "Pre-final question guard"),
    ("sequential_gate", "decide", "Compatibility slate gate"),
    ("gate_rank1", "decide", "Legacy gate-change branch"),
    ("keep_planned", "decide", "Keep dynamic slate"),
    ("persist_turn", "decide", "Persist action memory"),
    ("build_response", "decide", "Build official response"),
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
    """Initial circuit props: every production-observation node is pending."""

    nodes: dict[str, Any] = {}
    for node_id, stage, label in NODE_SPECS:
        extra = NODE_CATALOG.get(node_id) or {}
        nodes[node_id] = {
            "id": node_id,
            "stage": stage,
            "label": label,
            "status": "pending",
            "function": extra.get("function") or "",
            "implementation": (
                extra.get("implementation")
                or extra.get("how_it_works")
                or extra.get("meaning")
                or ""
            ),
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
        "stages": {
            name: {"status": "pending", "summary": ""}
            for name in STAGE_ORDER
        },
    }


def empty_inspect_turn(
    turn: int, original: str, nodes: dict[str, Any]
) -> dict[str, Any]:
    """One inspector turn row. ``nodes`` is the live circuit node map."""

    return {"turn": turn, "original": original, "nodes": nodes}


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Mutate circuit props from one production progress event."""

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
        if (
            stage_name in state["stages"]
            and state["stages"][stage_name]["status"] == "pending"
        ):
            state["stages"][stage_name]["status"] = "running"
    elif status == "error":
        state["status"] = "error"
        state["error"] = str(detail.get("error") or f"{node_id} failed")
        state["stages"][node["stage"]]["status"] = "error"
    return _refresh_progress(state)


def apply_understand_event(
    turn_state: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    """Fold understand-node details into the inspector row metadata."""

    if event.get("stage") != "understand":
        return turn_state
    node_id = str(event.get("node") or "")
    detail = event.get("detail")
    if not isinstance(detail, dict):
        return turn_state
    if node_id == "merge_rewrite":
        turn_state["rewritten"] = str(
            detail.get("rewritten")
            or (detail.get("output") or {}).get("rewritten")
            if isinstance(detail.get("output"), dict)
            else detail.get("rewritten")
            or ""
        )
        if detail.get("original") and not turn_state.get("original"):
            turn_state["original"] = str(detail["original"])
    elif node_id in {"turn_delta", "stage"}:
        _apply_understand_detail(turn_state, detail)
    return turn_state


def apply_understand_from_trace(
    turn_state: dict[str, Any], trace: TurnTrace
) -> dict[str, Any]:
    """Fill leftover understand fields from the finished trace."""

    _apply_understand_detail(turn_state, trace.understand)
    return turn_state


def finalize_circuit(
    state: dict[str, Any], trace: TurnTrace | None
) -> dict[str, Any]:
    """Close the circuit without rewriting genuinely skipped stage outcomes."""

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
        state["stages"]["router"]["summary"] = _stage_summary(
            "router", trace.router
        )
        state["stages"]["retrieve"]["summary"] = _stage_summary(
            "retrieve", trace.retrieve
        )
        state["stages"]["decide"]["summary"] = _stage_summary(
            "decide", trace.decide
        )
        for name in STAGE_ORDER:
            current = state["stages"][name]["status"]
            if current in {"pending", "running"}:
                state["stages"][name]["status"] = "completed"
    if state["status"] != "error":
        state["status"] = "completed"
    state["progressPercent"] = 100
    state["current"] = "build_response"
    state["activeGraph"] = "decide"
    return state


def _apply_understand_detail(
    turn_state: dict[str, Any], detail: dict[str, Any]
) -> None:
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


def _output(detail: dict[str, Any]) -> dict[str, Any]:
    value = detail.get("output")
    return value if isinstance(value, dict) else {}


def _from_io(detail: dict[str, Any], key: str, fallback: str = "") -> str:
    output = _output(detail)
    if output.get(key) not in (None, ""):
        return str(output[key])
    if detail.get(key) not in (None, ""):
        return str(detail[key])
    return fallback


def _node_caption(node_id: str, detail: dict[str, Any]) -> str:
    out = _output(detail)
    if node_id == "merge_rewrite":
        rewritten = str(
            out.get("rewritten") or detail.get("rewritten") or ""
        ).strip()
        if rewritten:
            return rewritten[:72]
    if node_id in {
        "color_map",
        "material_map",
        "color_verify",
        "material_verify",
    }:
        hits = detail.get("hits") or out.get("hits") or []
        return f"{len(hits)} hit" + ("" if len(hits) == 1 else "s")
    if node_id.startswith("category_l"):
        labels = detail.get("labels") or out.get("labels") or []
        return ", ".join(str(item) for item in labels) if labels else "none"
    if node_id == "category_cap":
        kept = detail.get("kept") or out.get("kept") or []
        if kept:
            return ", ".join(str(item) for item in kept)
    if node_id == "disclosure":
        flag = detail.get("empty", out.get("empty"))
        if flag is True:
            return "empty disclosure"
        if flag is False:
            return "shopping evidence"
    if node_id == "override_l1":
        flag = out.get("full", detail.get("full"))
        if flag is None:
            return ""
        return "full reset" if flag else "keep intent"
    if node_id == "override_l2":
        flag = out.get("override", detail.get("override"))
        if flag is None:
            return ""
        return "replace fields" if flag else "accumulate"
    if node_id in {"probe_override", "probe_before", "probe_after"}:
        exact = out.get("exact", detail.get("exact"))
        lenient = out.get("exact_lenient", detail.get("exact_lenient"))
        if exact is None:
            return "exact=None"
        suffix = "" if lenient is None else f" · lenient={lenient}"
        return f"exact={exact}{suffix}"
    if node_id == "route_llm":
        return _from_io(detail, "intention")
    if node_id in {"buying", "browsing", "intention_override"}:
        return _from_io(detail, "intention")
    if node_id == "select_pool":
        selected = out.get("selected")
        count = out.get("selected_count")
        if selected:
            return f"{selected} · {count if count is not None else 'None'}"
    if node_id == "slot_groups":
        required = out.get("required") or []
        preferred = out.get("preferred") or []
        return f"{len(required)} hard · {len(preferred)} soft"
    if node_id == "routing":
        library = out.get("library_limit")
        return "" if library is None else f"library={library}"
    if node_id in {
        "score_exact",
        "hybrid_search",
        "cap_hits",
        "base_only",
        "relaxed_route",
        "raw_text_route",
        "weighted_rrf",
    }:
        count = out.get("hit_count", out.get("scored"))
        path = out.get("path")
        if count is not None:
            return f"{count} hits" + (f" · {path}" if path else "")
    if node_id == "raw_evidence":
        if out.get("has_raw_evidence"):
            return f"{out.get('term_count', 0)} raw terms"
        return "no raw evidence"
    if node_id == "qwen_rerank":
        count = out.get("reranked_weights", out.get("reranked"))
        return "semantic" if count is None else f"semantic · {count} weights"
    if node_id == "belief_hits":
        count = out.get("weighted")
        return "belief" if count is None else f"belief · {count} weights"
    if node_id == "normalize":
        count = out.get("count", detail.get("count"))
        return "" if count is None else f"{count} ranked"
    if node_id == "eligible_questions":
        questions = out.get("questions") or []
        return f"{len(questions)} candidates"
    if node_id == "viability_filter":
        questions = out.get("planner_questions") or []
        return f"{len(questions)} viable"
    if node_id == "planning_head":
        head = out.get("head_count")
        tail = out.get("tail_probability")
        if head is not None:
            return f"head={head} · tail={tail}"
    if node_id == "action_space":
        count = out.get("action_count")
        return "" if count is None else f"{count} actions"
    if node_id == "planner":
        ask = out.get("ask_attribute") or "none"
        planned = out.get("planned")
        return f"ask={ask} · k={planned}"
    if node_id == "fallback_question":
        used = out.get("used")
        ask = out.get("ask_attribute") or "none"
        return f"{'used' if used else 'not needed'} · ask={ask}"
    if node_id == "sequential_gate":
        return "changed" if out.get("gated") else "no-op · unchanged"
    if node_id == "keep_planned":
        count = out.get("count")
        return "" if count is None else f"keep {count}"
    if node_id == "persist_turn":
        count = out.get("last_slate")
        ask = out.get("last_ask") or "none"
        return f"slate={count} · ask={ask}"
    if node_id == "build_response":
        recs = out.get("recommendations")
        ask = out.get("ask_attribute") or "none"
        if recs is not None:
            return f"{recs} recs · ask={ask}"
    if node_id == "turn_delta":
        source = detail.get("source") or out.get("source")
        return "" if source is None else f"source={source}"
    why = detail.get("why")
    if why:
        return str(why)[:72]
    return ""


def _stage_summary(stage: str, detail: dict[str, Any]) -> str:
    if stage == "understand":
        source = detail.get("source") or "-"
        category = detail.get("category") or "-"
        disclosure = "empty" if detail.get("disclosure_empty") else "evidence"
        return f"source={source}\ncategory={category}\n{disclosure}"
    if stage == "router":
        if detail.get("skipped"):
            return f"skipped\n{detail.get('reason') or '-'}"
        intention = detail.get("intention") or "-"
        strict = detail.get("exact")
        lenient = detail.get("exact_lenient")
        strict_bit = "None" if strict is None else str(strict)
        lenient_bit = "None" if lenient is None else str(lenient)
        return f"{intention}\nstrict={strict_bit}\nlenient={lenient_bit}"
    if stage == "retrieve":
        count = detail.get("hit_count")
        top = detail.get("top") or []
        head = top[0] if top else None
        extra = ""
        if isinstance(head, dict) and head.get("parent_asin"):
            routes = head.get("routes") or []
            route_bit = f" · {'+'.join(routes)}" if routes else ""
            extra = f"\ntop {head['parent_asin']}{route_bit}"
        return f"{count or 0} candidates{extra}"
    if stage == "decide":
        ask = detail.get("ask_attribute") or "none"
        slate = detail.get("slate")
        planned = detail.get("planned_slate")
        slate_n = len(slate) if isinstance(slate, list) else slate
        planned_n = len(planned) if isinstance(planned, list) else planned
        return f"ask={ask}\nslate={slate_n or 0}\nplanned={planned_n or 0}"
    return ""
