"""Retrieve layer: constraints → exact pool or BM25 → scored SearchHit.

Input: SessionState (category, ranking_constraints, excluded_asins, message).
Output: at most 500 SearchHit values.
Role: shrink the catalog; does not choose the question or how many products to show. See README.md.
"""

from .catalog import CatalogRetriever, SearchHit, build_response_signature
from .candidates import CandidateOrganizer, retrieve_candidates
from .filtering import ProductFilter, exact_pool

__all__ = [
    "CatalogRetriever",
    "CandidateOrganizer",
    "ProductFilter",
    "SearchHit",
    "build_response_signature",
    "exact_pool",
    "retrieve_candidates",
]
