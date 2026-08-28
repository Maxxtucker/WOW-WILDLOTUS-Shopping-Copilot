"""Purpose: candidate-fusion package.

Input: CatalogRetriever, SessionState, optional exact set.
Output: at most 500 SearchHit values.
Role: fold filter results or BM25 recall into one list. See README.md.
"""

from .query import rewrite_query
from .retrieve import CandidateOrganizer, retrieve_candidates
from .routing import TrackRouting, routing_for

__all__ = [
    "CandidateOrganizer",
    "TrackRouting",
    "retrieve_candidates",
    "rewrite_query",
    "routing_for",
]
