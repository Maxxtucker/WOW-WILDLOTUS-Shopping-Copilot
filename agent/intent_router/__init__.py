"""Purpose: intention router package (override vs accumulate, then buying/browsing).

Input: SessionState.turn_delta plus CatalogRetriever for exact-pool probes.
Output: state.intention and the exact ASIN set passed to retrieve.
Role: pipeline stage between understand observe and candidate organization.
"""

from .exact_pool import exact_pool, exact_pool_for_state, exact_pool_from_groups
from .llm import (
    IntentRouterClient,
    classify_override,
    classify_route,
    warmup_intent_router,
)
from .probe import pool_ratio, pool_size, probe_exact_pool
from .router import IntentRouter, route_intention
from .writeback import apply_delta, replace_with_delta

__all__ = [
    "IntentRouter",
    "IntentRouterClient",
    "apply_delta",
    "classify_override",
    "classify_route",
    "exact_pool",
    "exact_pool_for_state",
    "exact_pool_from_groups",
    "pool_ratio",
    "pool_size",
    "probe_exact_pool",
    "replace_with_delta",
    "route_intention",
    "warmup_intent_router",
]
