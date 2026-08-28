"""Purpose: category is a top-level extract field, not a constraint object.

Input: raw category value plus the user message.
Output: a copied span, or None if it is not in the message.
Role: the only category grounding path; constraints must not use attribute=category.
"""

from __future__ import annotations

from ...schema import ground_span


def ground_category(value: object, message: str) -> str | None:
    return ground_span(value, message)
