"""Purpose: exact-pool probe used by the intention router.

Input: CatalogRetriever and SessionState after (or before) delta commit.
Output: set of parent_asin, or None when a signal is missing from the index.
Role: count candidates without ranking. None is not the same as an empty set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exact_pool import exact_pool_for_state

if TYPE_CHECKING:
    from ..retrieve.catalog.retriever import CatalogRetriever
    from ..understand.state.session import SessionState


def probe_exact_pool(retriever: CatalogRetriever, state: SessionState) -> set[str] | None:
    return exact_pool_for_state(retriever, state)


def pool_size(exact: set[str] | None) -> int | None:
    if exact is None:
        return None
    return len(exact)


def pool_ratio(after: int | None, before: int | None) -> float | None:
    if after is None or before is None or before == 0:
        return None
    return after / before
