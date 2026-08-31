"""Purpose: cache “what this ASIN would answer if we asked attribute”.

Input: CatalogRetriever, SessionState (disclosed).
Output: answer_signature(parent_asin, attribute) → canonical value tuple or NO_ADDITIONAL.
Role: avoid repeating predict_reply during planner counterfactual expansion.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ...domain import canonical
from .types import NO_ADDITIONAL

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...understand.state.session import SessionState


def make_answer_signature(
    retriever: CatalogRetriever,
    state: SessionState,
) -> Callable[[str, str], tuple[str, ...]]:
    cache: dict[tuple[str, str], tuple[str, ...]] = {}

    def answer_signature(parent_asin: str, attribute: str) -> tuple[str, ...]:
        key = (parent_asin, attribute)
        if key not in cache:
            values = retriever.predict_reply(parent_asin, attribute, state.disclosed)
            cache[key] = (
                NO_ADDITIONAL
                if not values
                else tuple(canonical(value) for value in values)
            )
        return cache[key]

    return answer_signature
