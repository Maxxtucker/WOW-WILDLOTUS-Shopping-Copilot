"""Retrieve layer: constraints → exact pool or BM25 → scored SearchHit.

Input: SessionState (category, typed slots or ranking_constraints, excluded_asins, message).
Output: at most 500 SearchHit values.
Role: shrink the catalog; from_slots maps typed_constraints at retrieve time. See README.md.
"""

from .catalog import CatalogRetriever, SearchHit, build_response_signature
from .candidates import CandidateOrganizer, retrieve_candidates
from .filtering import ProductFilter, exact_pool, exact_pool_for_state

__all__ = [
    "CatalogRetriever",
    "CandidateOrganizer",
    "ProductFilter",
    "SearchHit",
    "build_response_signature",
    "exact_pool",
    "exact_pool_for_state",
    "retrieve_candidates",
]
