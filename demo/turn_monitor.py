"""Purpose: print one pipeline stage to the Chainlit terminal as the circuit reveals it.

Input: a progress event (stage completed) plus optional SessionState and retriever.
Output: flushed text on stdout. No files, no evaluator labels.
Role: demo diagnostics only. Agent.respond never registers a listener.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from agent.understand.observation.schema import ObservationExtract
from agent.understand.state import SessionState


def maybe_log_progress_event(
    event: dict[str, Any],
    *,
    turn: int | None,
    state: SessionState | None = None,
    retriever: object | None = None,
    stream: TextIO | None = None,
) -> None:
    """Print only on stage-completed reveals. Other circuit nodes stay quiet."""

    if event.get("node") != "stage" or event.get("status") != "completed":
        return
    detail = event.get("detail")
    if not isinstance(detail, dict):
        detail = {}
    log_stage_reveal(
        turn=turn,
        stage=str(event.get("stage") or ""),
        detail=detail,
        state=state,
        retriever=retriever,
        stream=stream,
    )


def log_stage_reveal(
    *,
    turn: int | None,
    stage: str,
    detail: dict[str, Any],
    state: SessionState | None = None,
    retriever: object | None = None,
    stream: TextIO | None = None,
) -> None:
    """Dump the stage payload plus a compact session snapshot."""

    out = stream or sys.stdout
    label = stage.strip() or "stage"
    turn_bit = "-" if turn is None else str(turn)
    lines = [f"======== turn {turn_bit} / {label} ========", ""]
    if label == "understand":
        lines.extend(_understand_lines(detail))
    elif label == "router":
        lines.extend(_router_lines(detail))
    elif label == "retrieve":
        lines.extend(_retrieve_lines(detail, retriever))
    elif label == "decide":
        lines.extend(_decide_lines(detail, retriever))
    else:
        lines.append(_dumps(detail))
    lines.extend(["", "--- session ---", _dumps(session_snapshot(state))])
    print("\n".join(lines), file=out, flush=True)


def session_snapshot(state: SessionState | None) -> dict[str, Any]:
    """Committed memory after this stage. Omits profile and message history."""

    if state is None:
        return {}
    return {
        "category": state.category,
        "intention": state.intention,
        "gate_open": state.gate_open,
        "typed_constraints": _slot_rows(state.typed_constraints),
        "last_ask": state.last_ask,
        "asked": list(state.asked),
        "candidate_count": state.candidate_count,
        "last_slate": list(state.last_slate),
        "excluded_count": len(state.excluded_asins),
        "turn_delta": _delta_brief(state.turn_delta),
    }


def _understand_lines(detail: dict[str, Any]) -> list[str]:
    return [
        "--- turn_delta ---",
        _dumps(
            {
                "source": detail.get("source"),
                "category": detail.get("category"),
                "empty": detail.get("empty"),
                "slots": _slot_rows(detail.get("slots") or []),
            }
        ),
    ]


def _router_lines(detail: dict[str, Any]) -> list[str]:
    return [
        "--- router ---",
        _dumps(
            {
                "intention": detail.get("intention"),
                "override": detail.get("override"),
                "exact": detail.get("exact"),
                "pool_before": detail.get("pool_before"),
                "pool_after": detail.get("pool_after"),
                "ratio": detail.get("ratio"),
                "hard_groups": detail.get("hard_groups") or [],
                "exact_sample": detail.get("exact_sample"),
            }
        ),
    ]


def _retrieve_lines(detail: dict[str, Any], retriever: object | None) -> list[str]:
    lines = [
        "--- retrieve ---",
        f"hit_count={detail.get('hit_count', 0)}  scored_exact={detail.get('scored_exact')}",
        "",
        "--- retrieve top 10 ---",
    ]
    lines.extend(_hit_lines(detail.get("top") or [], retriever, score_key="score"))
    lines.extend(["", "--- ranked top 10 ---"])
    lines.extend(
        _hit_lines(detail.get("ranked_top") or [], retriever, score_key="probability")
    )
    return lines


def _decide_lines(detail: dict[str, Any], retriever: object | None) -> list[str]:
    response = detail.get("response")
    if not isinstance(response, dict):
        response = {}
    recs = [str(item) for item in response.get("recommendations") or []]
    lines = [
        "--- decide ---",
        _dumps(
            {
                "ask_attribute": detail.get("ask_attribute"),
                "reason": detail.get("reason"),
                "gated": detail.get("gated"),
                "planned_slate": detail.get("planned_slate") or [],
                "slate": detail.get("slate") or [],
            }
        ),
        "",
        "--- respond ---",
        f"ask_attribute={response.get('ask_attribute')}",
        str(response.get("message") or ""),
    ]
    if recs:
        lines.append("")
        lines.extend(_asin_lines(recs, retriever))
    return lines


def _slot_rows(slots: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slot in slots or ():
        if hasattr(slot, "as_dict"):
            raw = slot.as_dict()
        elif isinstance(slot, dict):
            raw = dict(slot)
        else:
            continue
        rows.append(
            {
                "attribute": raw.get("attribute"),
                "surface": raw.get("surface"),
                "canonical": raw.get("canonical"),
                "is_hard": raw.get("is_hard"),
            }
        )
    return rows


def _delta_brief(delta: ObservationExtract | None) -> dict[str, Any] | None:
    if delta is None:
        return None
    return {
        "source": delta.source,
        "category": delta.category,
        "empty": delta.empty,
        "slots": _slot_rows(delta.slots),
    }


def _hit_lines(
    rows: list[Any],
    retriever: object | None,
    *,
    score_key: str,
) -> list[str]:
    if not rows:
        return ["(empty)"]
    lines: list[str] = []
    for index, row in enumerate(rows[:10], start=1):
        if not isinstance(row, dict):
            lines.append(f"{index}. {row}")
            continue
        asin = str(row.get("parent_asin") or "")
        score = row.get(score_key)
        matched = row.get("matched_constraints") or []
        title = _product_title(retriever, asin)
        extra = f"  {score_key}={score}" if score is not None else ""
        match_bit = f"  matched={matched}" if matched else ""
        lines.append(f"{index}. {title}  {asin}{extra}{match_bit}")
    return lines


def _asin_lines(asins: list[str], retriever: object | None) -> list[str]:
    lines: list[str] = []
    for index, asin in enumerate(asins, start=1):
        title = _product_title(retriever, asin)
        lines.append(f"{index}. {title}  {asin}")
    return lines


def _product_title(retriever: object | None, parent_asin: str) -> str:
    if retriever is None or not parent_asin:
        return parent_asin or "-"
    getter = getattr(retriever, "get_product", None)
    if getter is None:
        return parent_asin
    product = getter(parent_asin) or {}
    return str(product.get("title") or parent_asin)


def _dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
