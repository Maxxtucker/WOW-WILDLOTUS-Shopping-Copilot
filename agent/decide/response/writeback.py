"""Purpose: write this turn's action back into SessionState for next-turn parsing.

Input: state, retriever, candidate ASINs, Plan, slate.
Output: updates last_slate, last_ask, asked, reply_value_lookup.
Role: next-turn miss feedback and semicolon restore both depend on this.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...understand.attributes.lookup import build_reply_lookup

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ..clarification.types import Plan
    from ...understand.state.session import SessionState


def record_action(
    state: SessionState, slate: list[str], ask_attribute: str | None
) -> None:
    state.last_slate = list(slate)
    state.last_gate_open = state.gate_open
    state.last_ask = ask_attribute
    state.shown_asins.update(slate)
    if ask_attribute:
        state.asked.append(ask_attribute)


def set_reply_options(state: SessionState, options: list[tuple[str, ...]]) -> None:
    state.reply_value_lookup = build_reply_lookup(options)


def persist_turn(
    state: SessionState,
    retriever: CatalogRetriever,
    candidate_asins: Sequence[str],
    plan: Plan,
    slate: list[str],
) -> None:
    if plan.ask_attribute is None:
        set_reply_options(state, [])
    else:
        set_reply_options(
            state,
            [
                retriever.predict_reply(
                    parent_asin,
                    plan.ask_attribute,
                    state.disclosed,
                )
                for parent_asin in candidate_asins
            ],
        )
    record_action(state, slate, plan.ask_attribute)
