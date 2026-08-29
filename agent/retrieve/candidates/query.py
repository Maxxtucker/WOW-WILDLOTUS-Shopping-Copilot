"""Purpose: rewrite only the active intent into a BM25 query.

Input: SessionState. Optional string constraints override only the regex fallback.
Output: (query: str, profile dimension tags for downstream use).
Role: supply clean active terms to catalog.search without replaying old/negated text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..from_slots import query_terms

if TYPE_CHECKING:
    from ...understand.state.session import SessionState


def rewrite_query(
    state: SessionState,
    constraints: tuple[str, ...] | None = None,
) -> tuple[str, list]:
    """Build a query from committed state, not raw dialogue or profile labels."""

    terms = constraints if constraints is not None else query_terms(state)
    profile_tags = list(state.preference_tags)
    query = " ".join(
        part
        for part in (
            state.category or "",
            *terms,
        )
        if part
    )
    # A message-only fallback preserves recall when observation extracted no
    # active evidence. Once slots exist, replaying the raw message can restore
    # negated or superseded terms after an intent override.
    if not query.strip():
        query = state.latest_message.strip()
    return query, list(profile_tags)
