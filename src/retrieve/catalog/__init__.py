"""Purpose: catalog retrieval package.

Input: catalog.jsonl path, query/constraints/ASIN.
Output: SearchHit, ResponseSignature, parent_asin sets, predicted replies.
Role: retrieve infrastructure; public API does not depend on SessionState. See README.md.
"""

from .protocol_copy import (
    ALLOWED_ATTRIBUTES,
    classify_constraint,
    coarse_category,
    normalize_text,
    searchable_text,
    tokenize,
)
from .retriever import CatalogRetriever, Retriever
from .signatures import build_response_signature, coerce_constraints
from .types import ResponseSignature, SearchHit, SearchWeights

_coerce_constraints = coerce_constraints

__all__ = [
    "ALLOWED_ATTRIBUTES",
    "CatalogRetriever",
    "ResponseSignature",
    "Retriever",
    "SearchHit",
    "SearchWeights",
    "build_response_signature",
    "classify_constraint",
    "coarse_category",
    "normalize_text",
    "searchable_text",
    "tokenize",
    "_coerce_constraints",
]
