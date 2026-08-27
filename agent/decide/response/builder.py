"""Purpose: assemble slate and ask_attribute into the official respond dict.

Input: SessionState, retriever, hits, Plan, slate.
Output: {message, ask_attribute, recommendations, usage}.
Role: external shape of pipeline stage 8; usage is always 0 (no LLM).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..clarification.questions import explain_question
from .writeback import persist_turn

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...retrieve.catalog.types import SearchHit
    from ..clarification.types import Plan
    from ...understand.state.session import SessionState


class ResponseBuilder:
    """Stage 8: write session memory and return the protocol dict."""

    def apply(
        self,
        state: SessionState,
        retriever: CatalogRetriever,
        hits: list[SearchHit],
        plan: Plan,
        slate: list[str],
    ) -> dict:
        persist_turn(state, retriever, hits, plan, slate)
        return build_response(slate, plan.ask_attribute)


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


def build_response(slate: list[str], ask_attribute: str | None) -> dict:
    return {
        "message": build_message(slate, ask_attribute),
        "ask_attribute": ask_attribute,
        "recommendations": [
            {"parent_asin": parent_asin} for parent_asin in slate
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }
