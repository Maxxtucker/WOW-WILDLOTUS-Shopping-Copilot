"""Purpose: rewrite current intent into a BM25 query and extract soft profile preferences.

Input: SessionState. Optional string constraints override only the regex fallback.
Output: (query: str, profile_tags: list).
Role: supply terms to catalog.search when the exact path fails.
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
    """Build the BM25 query and the soft profile tags used as preferred constraints."""

    terms = constraints if constraints is not None else query_terms(state)
    profile_tags = state.user_profile.get("preference_tags") or []
    profile_text = " ".join(str(value) for value in profile_tags[:4])
    query = " ".join(
        part
        for part in (
            state.category or "",
            *terms,
            state.latest_message,
            profile_text,
        )
        if part
    )
    return query, list(profile_tags)
