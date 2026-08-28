"""Retrieve layer: score the router exact pool, or BM25 when that pool is None.

Input: SessionState (typed slots, excluded_asins, message) plus optional exact ASINs.
Output: at most 500 SearchHit values.
Role: from_slots maps typed_constraints at score time. Hard intersection is the router.
"""

from .catalog import CatalogRetriever, SearchHit, build_response_signature
from .candidates import CandidateOrganizer, retrieve_candidates

__all__ = [
    "CatalogRetriever",
    "CandidateOrganizer",
    "SearchHit",
    "build_response_signature",
    "retrieve_candidates",
]
