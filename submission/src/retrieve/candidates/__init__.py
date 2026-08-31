"""Purpose: candidate-fusion package.

Input: CatalogRetriever, SessionState, optional exact set.
Output: SearchHit library (at least 300 when exact is small; browsing 500).
Role: score the router exact set; hybrid-fill to 300 when under 150. See README.md.
"""

from .query import rewrite_query
from .retrieve import CandidateOrganizer, retrieve_candidates
from .routing import LIBRARY_MIN, TrackRouting, library_limit_for, routing_for

__all__ = [
    "CandidateOrganizer",
    "LIBRARY_MIN",
    "TrackRouting",
    "library_limit_for",
    "retrieve_candidates",
    "rewrite_query",
    "routing_for",
]
