"""Purpose: attribute-capture package.

Input: SessionState, message text.
Output: active_constraints, disclosed, no_preference, reply-restore results.
Role: constraint accumulation, not prose understanding. See README.md.
"""

from .capture import (
    AttributeCapture,
    add_constraint,
    capture_colon_paraphrase,
    capture_matters,
    capture_no_additional,
    capture_no_preference,
    capture_reply_attributes,
    capture_turn1_generic_fallback,
)
from .lookup import build_reply_lookup, resolve_matters_pieces

__all__ = [
    "AttributeCapture",
    "add_constraint",
    "build_reply_lookup",
    "capture_colon_paraphrase",
    "capture_matters",
    "capture_no_additional",
    "capture_no_preference",
    "capture_reply_attributes",
    "capture_turn1_generic_fallback",
    "resolve_matters_pieces",
]
