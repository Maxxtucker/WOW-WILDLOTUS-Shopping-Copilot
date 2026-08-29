"""Purpose: assemble slate and ask_attribute into the official respond dict.

Input: SessionState, retriever, candidate ASINs, Plan, slate.
Output: {message, ask_attribute, recommendations, usage}.
Role: external shape of pipeline stage 8; usage includes intention-router tokens.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...progress import emit
from ..clarification.questions import explain_question
from .writeback import persist_turn

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ..clarification.types import Plan
    from ...understand.state.session import SessionState


class ResponseBuilder:
    """Stage 8: write session memory and return the protocol dict."""

    def apply(
        self,
        state: SessionState,
        retriever: CatalogRetriever,
        candidate_asins: Sequence[str],
        plan: Plan,
        slate: list[str],
    ) -> dict:
        emit("decide", "persist_turn", "running")
        persist_turn(state, retriever, candidate_asins, plan, slate)
        emit(
            "decide",
            "persist_turn",
            "completed",
            {
                "input": {
                    "ask_attribute": plan.ask_attribute,
                    "slate": len(slate),
                    "candidates": len(candidate_asins),
                },
                "output": {
                    "last_ask": state.last_ask,
                    "last_slate": len(state.last_slate),
                },
            },
        )
        emit("decide", "build_response", "running")
        response = build_response(
            slate,
            plan.ask_attribute,
            prompt_tokens=state.router_prompt_tokens,
            completion_tokens=state.router_completion_tokens,
        )
        emit(
            "decide",
            "build_response",
            "completed",
            {
                "output": {
                    "ask_attribute": response.get("ask_attribute"),
                    "recommendations": len(response.get("recommendations") or []),
                    "message": str(response.get("message") or "")[:160],
                },
            },
        )
        return response


def build_message(slate: list[str], ask_attribute: str | None) -> str:
    if slate:
        prefix = f"I narrowed this to {len(slate)} high-confidence option"
        if len(slate) != 1:
            prefix += "s"
        return f"{prefix}. {explain_question(ask_attribute)}"
    return (
        "I am narrowing the catalog before showing a low-confidence match. "
        + explain_question(ask_attribute)
    )


def build_response(
    slate: list[str],
    ask_attribute: str | None,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> dict:
    return {
        "message": build_message(slate, ask_attribute),
        "ask_attribute": ask_attribute,
        "recommendations": [
            {"parent_asin": parent_asin} for parent_asin in slate
        ],
        "usage": {
            "prompt_tokens": max(0, int(prompt_tokens)),
            "completion_tokens": max(0, int(completion_tokens)),
        },
    }
