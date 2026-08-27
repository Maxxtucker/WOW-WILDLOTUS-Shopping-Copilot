"""Purpose: rewrite current intent into a BM25 query and extract soft profile preferences.

Input: SessionState, ranking_constraints.
Output: (query: str, profile_tags: list).
Role: supply terms to catalog.search when the exact path fails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...understand.state.session import SessionState


def rewrite_query(state: SessionState, constraints: tuple[str, ...]) -> tuple[str, list]:
    """Build the BM25 query and the soft profile tags used as preferred constraints."""

    profile_tags = state.user_profile.get("preference_tags") or []
    profile_text = " ".join(str(value) for value in profile_tags[:4])
    query = " ".join(
        part
        for part in (
            state.category or "",
            *constraints,
            state.latest_message,
            profile_text,
        )
        if part
    )
    return query, list(profile_tags)
