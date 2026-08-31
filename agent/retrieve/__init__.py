"""Retrieve layer: exact/hybrid recall, safety-route fusion, and ranking input.

Input: SessionState (typed slots, excluded_asins, message) plus optional exact ASINs.
Output: at most 500 SearchHit values after optional weighted RRF.
Role: from_slots maps typed constraints; Intent Router owns the hard intersection.
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
