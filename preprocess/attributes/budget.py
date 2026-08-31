"""Purpose: copy catalog list price as a parseable budget amount (no comparison op)."""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..types import SlotRecord
from ._common import dedupe, slot


def _price(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        amount = float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount < 0:
        return None
    return amount


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    amount = _price(product.get("price"))
    if amount is None:
        return []
    label = format(amount, "g")
    return dedupe(
        [
            slot(
                "budget",
                label,
                label,
                "price",
                {"amount": amount},
                fold=False,
            )
        ]
    )
