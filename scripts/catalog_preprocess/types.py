"""Purpose: one extracted catalog slot aligned with ConstraintSlot attribute keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SlotRecord:
    attribute: str
    canonical: str
    surface: str
    source: str
    extras: dict[str, Any] | None = None
