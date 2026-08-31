"""Purpose: shared slot dataclasses and size/budget type aliases.

Input: grounded field values from an attribute handler.
Output: ConstraintSlot rows and GroundingFailures for repair.
Role: one slot shape for every attribute; handlers fill only the fields they own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ConstraintOp = Literal["lte", "gte", "eq"]
SizeSystem = Literal["us", "uk", "eu"]
SizeKind = Literal["shoe", "apparel", "dimension"]
SizeUnit = Literal["in"]

OR_ATTRIBUTES = frozenset(
    {"color", "material", "style", "brand", "feature", "use_case", "other"}
)


@dataclass(frozen=True, slots=True)
class ConstraintSlot:
    """One typed requirement. ``surface`` is what grounding checks.

    ``canonical`` is a tuple of alternatives (OR) before writeback splits
    one value per row. ``is_hard`` is a user-language lock, not a catalog fingerprint.
    """

    attribute: str
    surface: str
    canonical: tuple[str, ...] | None = None
    amount: float | None = None
    op: ConstraintOp | None = None
    system: SizeSystem | None = None
    kind: SizeKind | None = None
    unit: SizeUnit | None = None
    length: float | None = None
    width: float | None = None
    height: float | None = None
    weight: float | None = None
    is_hard: bool = True

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "attribute": self.attribute,
            "surface": self.surface,
            "is_hard": self.is_hard,
        }
        if self.canonical is not None:
            row["canonical"] = list(self.canonical)
        if self.amount is not None:
            row["amount"] = self.amount
        if self.op is not None:
            row["op"] = self.op
        if self.system is not None:
            row["system"] = self.system
        if self.kind is not None:
            row["kind"] = self.kind
        if self.unit is not None:
            row["unit"] = self.unit
        if self.length is not None:
            row["length"] = self.length
        if self.width is not None:
            row["width"] = self.width
        if self.height is not None:
            row["height"] = self.height
        if self.weight is not None:
            row["weight"] = self.weight
        return row

    def __post_init__(self) -> None:
        value = self.canonical
        if isinstance(value, str):
            object.__setattr__(self, "canonical", (value,) if value else None)
        elif value is not None and not isinstance(value, tuple):
            object.__setattr__(self, "canonical", tuple(value))


@dataclass(frozen=True, slots=True)
class ParsedItem:
    """Raw constraint after attribute/surface parse, before attribute grounding."""

    attribute: str
    surface: str
    canonical_hints: tuple[str, ...]
    amount: float | None
    op: ConstraintOp | None
    extras: tuple[str, ...]
    raw: Any = None
    alt_surfaces: tuple[str, ...] = ()
    is_hard: bool = True

    @property
    def canonical_hint(self) -> str | None:
        return self.canonical_hints[0] if self.canonical_hints else None


@dataclass
class GroundingFailures:
    """Raw payload pieces that did not survive surface grounding."""

    category: bool = False
    provisional_hint: bool = False
    override_value: bool = False
    constraints: list[Any] = field(default_factory=list)

    def __bool__(self) -> bool:
        return (
            self.category
            or self.provisional_hint
            or self.override_value
            or bool(self.constraints)
        )
