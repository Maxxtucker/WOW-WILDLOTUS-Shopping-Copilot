"""Purpose: map agent progress events onto Chainlit circuit and inspector props.

Input: ProgressEvent dicts from agent.progress plus an optional TurnTrace.
Output: JSON-safe props for PipelineCircuit and NodeInspector.
Role: UI state only. Does not run or alter the recommendation pipeline.
"""

from __future__ import annotations

import time
from typing import Any

from agent.trace import TurnTrace
from demo.workflow_schema import (
    STAGE_ORDER,
    WORKFLOW_SCHEMA,
    workflow_graph_props,
)

NODE_SPECS: tuple[tuple[str, str, str], ...] = tuple(
    (node_id, stage, metadata["label"])
    for stage in STAGE_ORDER
    for node_id, metadata in WORKFLOW_SCHEMA[stage]["nodes"].items()
)

DONE = frozenset({"completed", "skipped", "error"})

GRAPH_FOR_STAGE = {stage: stage for stage in STAGE_ORDER}

NEXT_GRAPH = {
    stage: STAGE_ORDER[index + 1]
    for index, stage in enumerate(STAGE_ORDER[:-1])
}


def empty_circuit_state() -> dict[str, Any]:
    """Initial circuit props: every production-observation node is pending."""

    nodes: dict[str, Any] = {}
    for node_id, stage, label in NODE_SPECS:
        metadata = WORKFLOW_SCHEMA[stage]["nodes"][node_id]
        nodes[node_id] = {
            "id": node_id,
            "stage": stage,
            "label": label,
            "status": "pending",
            "task": metadata["task"],
            "rationale": metadata["rationale"],
            "implementation": metadata["implementation"],
        }
    return {
        "title": "Agent pipeline",
        "status": "running",
        "current": "prior_miss",
        "activeGraph": "understand",
        "viewGraph": "",
        "selectedNode": "",
        "turn": 0,
        "progressPercent": 0,
        "error": "",
        "startedAt": time.time(),
        "nodes": nodes,
        "graphs": workflow_graph_props(),
        "graphOrder": list(STAGE_ORDER),
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
        state["status"] = "completed"
        state["error"] = ""
    elif state["status"] != "error":
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
    if node_id == "understand_mode":
        return _from_io(detail, "selected_path")
    if node_id == "nlu_attempt":
        used = out.get("attempts_used")
        source = out.get("source") or out.get("fallback")
        if used is None:
            return ""
        return f"attempts={used}" + (f" · {source}" if source else "")
    if node_id == "regex_extract":
        return _from_io(detail, "source") or "regex"
    if node_id == "colon_restore":
        applied = out.get("applied")
        if applied is True:
            return "restored"
        if applied is False:
            return "not applied"
    if node_id == "empty_disclosure_gate":
        return _from_io(detail, "path")
    if node_id == "committed_intent":
        flag = out.get("has_committed_intent")
        if flag is True:
            return "prior intent"
        if flag is False:
            return "no prior intent"
    if node_id == "strong_override_fallback":
        matched = out.get("matched")
        if matched is True:
            return "explicit start-over"
        if matched is False:
            return "no match"
    if node_id == "pool_ratio":
        ratio = out.get("ratio")
        if ratio is None and out.get("defined") is False:
            return "undefined"
        if ratio is not None:
            return f"ratio={ratio}"
    if node_id == "profile_diagnostic":
        return "computed · weight 0"
    if node_id == "weighted_score":
        formula = detail.get("input", {}).get("formula") if isinstance(detail.get("input"), dict) else None
        return str(formula)[:72] if formula else ""
    if node_id == "epsilon_roll":
        return _from_io(detail, "selection_mode") or _from_io(detail, "branch")
    if node_id in {"technical_exploit", "uniform_explore", "selected_attribute"}:
        return _from_io(detail, "ask_attribute")
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
