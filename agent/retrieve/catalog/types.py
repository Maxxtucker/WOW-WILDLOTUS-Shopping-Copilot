"""Purpose: public retrieval data types (SearchHit, ResponseSignature, weights).

Input: index rows / signature JSON / scoring intermediates.
Output: frozen dataclasses used by candidates, the router probe, and decide.
Role: catalog's structural contract; no SessionState dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias

from .protocol_copy import normalise_attribute, normalize_text


ConstraintInput: TypeAlias = (
    Mapping[str, object]
    | Iterable[tuple[str, object] | str]
    | tuple[str, object]
    | str
    | None
)
BudgetInput: TypeAlias = (
    float
    | int
    | str
    | tuple[float | None, float | None]
    | list[float | None]
    | None
)


def tuple_mapping(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, items in value.items():
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            result[str(key)] = tuple(str(item) for item in items)
    return result


@dataclass(frozen=True, slots=True)
class SearchWeights:
    """Weights used to combine lexical, structured, and catalog priors."""

    lexical: float = 1.0
    required: float = 5.0
    preferred: float = 1.75
    category: float = 3.0
    budget: float = 1.25
    rating: float = 0.08
    popularity: float = 0.12
    missing_required: float = -0.35
    excluded: float = -8.0
    dimension: float = 1.75
    text: float = 1.0
    profile: float = 0.3


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    """Catalog L/W/H in inches and weight in pounds. op is eq, lte, or gte."""

    length: float | None = None
    width: float | None = None
    height: float | None = None
    weight: float | None = None
    op: str = "eq"


@dataclass(frozen=True, slots=True)
class ResponseSignature:
    """Product values relevant to retrieval and deterministic dialog replies.

    ``response_values`` contains only values the current official simulator can
    disclose for each ``ask_attribute``.  ``search_values`` additionally
    contains catalog-derived aliases such as category and store/brand.  Keeping
    the two mappings separate prevents the question planner from hallucinating
    that a brand or category answer will be revealed when the simulator's
    constraint classifier cannot produce one.
    """

    target_category: str
    hard_constraints: tuple[str, ...]
    soft_preferences: tuple[str, ...]
    response_values: Mapping[str, tuple[str, ...]] = field(repr=False)
    search_values: Mapping[str, tuple[str, ...]] = field(repr=False)

    @property
    def constraints(self) -> tuple[str, ...]:
        return self.hard_constraints + self.soft_preferences

    def expected_reply(
        self,
        attribute: str,
        disclosed: Iterable[str] = (),
        *,
        limit: int = 2,
    ) -> tuple[str, ...]:
        """Return values the official simulator would reveal for ``attribute``.

        The caller remains responsible for the evaluator's first empty
        Boundary reply because that is session-specific, not a property of
        the product.
        """

        attr = normalise_attribute(attribute)
        disclosed_norm = {normalize_text(value) for value in disclosed}
        if attr == "other":
            values = self.constraints
        else:
            values = self.response_values.get(attr, ())
        return tuple(
            value
            for value in values
            if normalize_text(value) not in disclosed_norm
        )[: max(0, limit)]

    def to_dict(self) -> dict[str, object]:
        return {
            "target_category": self.target_category,
            "hard_constraints": list(self.hard_constraints),
            "soft_preferences": list(self.soft_preferences),
            "response_values": {
                key: list(values) for key, values in self.response_values.items()
            },
            "search_values": {
                key: list(values) for key, values in self.search_values.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ResponseSignature":
        response_payload = payload.get("response_values")
        search_payload = payload.get("search_values")
        return cls(
            target_category=str(payload.get("target_category") or "product"),
            hard_constraints=tuple(
                str(value) for value in payload.get("hard_constraints", []) or []
            ),
            soft_preferences=tuple(
                str(value) for value in payload.get("soft_preferences", []) or []
            ),
            response_values=tuple_mapping(response_payload),
            search_values=tuple_mapping(search_payload),
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One ranked catalog candidate with inspectable score components."""

    parent_asin: str
    score: float
    lexical_score: float
    structured_score: float
    prior_score: float
    required_coverage: float
    matched_constraints: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def recommendation(self, *, include_score: bool = False) -> dict[str, object]:
        result: dict[str, object] = {"parent_asin": self.parent_asin}
        if include_score:
            result["score"] = self.score
        return result


_tuple_mapping = tuple_mapping
