"""Purpose: candidate-fusion package.

Input: CatalogRetriever, SessionState, optional exact set.
Output: at most 500 SearchHit values.
Role: fold filter results or BM25 recall into one list. See README.md.
"""

from .query import rewrite_query
from .retrieve import CandidateOrganizer, retrieve_candidates

__all__ = ["CandidateOrganizer", "retrieve_candidates", "rewrite_query"]
