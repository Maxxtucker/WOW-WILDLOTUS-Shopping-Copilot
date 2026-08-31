"""Purpose: budget slot grounding from a message digit and comparison op.

Input: parsed budget item, grounded surface, user message.
Output: ConstraintSlot with amount and op, or None if no digit grounds.
Role: surface may be digits only; amount must appear in the message.
"""

from __future__ import annotations

from ..text import infer_op, parse_amount
from ..types import ConstraintSlot, ParsedItem


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    del message
    amount = parsed.amount
    if amount is None:
        amount = parse_amount(surface)
    if amount is None:
        return None
    op = parsed.op or infer_op(surface)
    return ConstraintSlot(
        attribute="budget",
        surface=surface,
        amount=amount,
        op=op,
    )
