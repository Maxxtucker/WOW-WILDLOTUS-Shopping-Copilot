"""Purpose: attribute-capture package.

Input: SessionState, constraint string.
Output: active_constraints, disclosed, reply-restore results.
Role: constraint accumulation and semicolon restore. See README.md.
"""

from .capture import add_constraint
from .lookup import build_reply_lookup, resolve_matters_pieces

__all__ = [
    "add_constraint",
    "build_reply_lookup",
    "resolve_matters_pieces",
]
