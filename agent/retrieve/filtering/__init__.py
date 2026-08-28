"""Purpose: hard-filter package.

Input: CatalogRetriever, SessionState (category + groups from from_slots).
Output: set[parent_asin] or None (drop the exact path if a signal is missing).
Role: retrieve's first cut; exact intersection only. See README.md.
"""

from .exact_pool import ProductFilter, exact_pool, exact_pool_for_state

__all__ = ["ProductFilter", "exact_pool", "exact_pool_for_state"]
