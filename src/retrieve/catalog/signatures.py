"""Purpose: build ResponseSignature from product metadata and normalize retrieval constraint/budget input.

Input: catalog product dict, or required/preferred constraints in various shapes.
Output: ResponseSignature, or (attribute, value) pairs / budget interval.
Role: turn the evaluator intent card into index keys that can be intersected and used to predict replies.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from .protocol_copy import (
    ALLOWED_ATTRIBUTES,
    COLOR_RE,
    MATERIAL_RE,
    MONEY_RE,
    category_values,
    classify_constraint,
    intent_card,
    normalise_attribute,
    normalize_text,
    ordered_unique,
    searchable_text,
    tokenize,
)
from .types import BudgetInput, ConstraintInput, ResponseSignature


def build_response_signature(product: Mapping[str, object]) -> ResponseSignature:
    """Build an evaluator-compatible intent card plus retrieval aliases."""

    card = intent_card(product)
    title = str(card["target_category"])
    corpus = searchable_text(product)
    material = MATERIAL_RE.search(corpus)
    color = COLOR_RE.search(corpus)
    hard = tuple(str(value) for value in card["hard_constraints"])
    soft = tuple(str(value) for value in card["soft_preferences"])
    all_constraints = hard + soft

    response_values_lists: dict[str, list[str]] = {
        attribute: [] for attribute in ALLOWED_ATTRIBUTES
    }
    for constraint in all_constraints:
        response_values_lists[classify_constraint(constraint)].append(constraint)
    response_values_lists["other"] = list(all_constraints)

    search_values_lists = {
        key: list(values) for key, values in response_values_lists.items()
    }
    search_values_lists["category"].extend(category_values(product))
    if product.get("store") not in (None, ""):
        search_values_lists["brand"].append(str(product["store"]))
    # These corpus-derived aliases help robust search but do not change what
    # expected_reply() predicts for the official customer simulator.
    if material:
        search_values_lists["material"].append(material.group(1).lower())
    if color:
        search_values_lists["color"].append(f"color: {color.group(1).lower()}")
    if product.get("price") not in (None, ""):
        search_values_lists["budget"].append(f"budget around ${product['price']}")

    response_values = {
        key: ordered_unique(values)
        for key, values in response_values_lists.items()
        if values
    }
    search_values = {
        key: ordered_unique(values)
        for key, values in search_values_lists.items()
        if values
    }
    return ResponseSignature(
        target_category=title,
        hard_constraints=hard,
        soft_preferences=soft,
        response_values=response_values,
        search_values=search_values,
    )


def value_aliases(attribute: str, value: object) -> tuple[str, ...]:
    attr = normalise_attribute(attribute)
    text = normalize_text(value)
    aliases: list[str] = [text] if text else []
    if ":" in str(value):
        aliases.append(normalize_text(str(value).split(":", 1)[1]))
    if attr == "material":
        match = MATERIAL_RE.search(str(value))
        if match:
            aliases.append(normalize_text(match.group(1)))
    elif attr == "color":
        match = COLOR_RE.search(str(value))
        if match:
            aliases.append(normalize_text(match.group(1)))
    elif attr == "budget":
        match = MONEY_RE.search(str(value).replace(",", ""))
        if match:
            amount = float(match.group(1))
            aliases.extend((f"{amount:g}", f"budget {amount:g}"))
    return ordered_unique(aliases)


def coerce_constraints(value: ConstraintInput) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return ((classify_constraint(value), value),) if value.strip() else ()
    if isinstance(value, Mapping):
        pairs: list[tuple[str, str]] = []
        for attribute, raw_values in value.items():
            if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
                iterable = raw_values
            else:
                iterable = [raw_values]
            for raw in iterable:
                if raw not in (None, ""):
                    pairs.append((normalise_attribute(attribute), str(raw)))
        return tuple(pairs)
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and not isinstance(value[1], tuple)
    ):
        # A two-item tuple is ambiguous: it can be one explicit
        # ``(attribute, value)`` pair or two independent constraints.  Treat it
        # as a pair only when the first value is a real attribute name/alias;
        # otherwise the iterable branch below must classify both strings.
        raw_attribute = value[0].strip().casefold().replace("-", "_")
        attribute_aliases = {
            "categories",
            "materials",
            "colours",
            "colour",
            "colors",
            "sizes",
            "brands",
            "price",
            "features",
            "usecase",
            "use cases",
        }
        if raw_attribute in ALLOWED_ATTRIBUTES or raw_attribute in attribute_aliases:
            return ((normalise_attribute(value[0]), str(value[1])),)

    result: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                result.append((classify_constraint(item), item))
        elif isinstance(item, Sequence) and len(item) == 2:
            result.append((normalise_attribute(item[0]), str(item[1])))
        else:
            raise TypeError(f"Unsupported constraint item: {item!r}")
    return tuple(result)


def coerce_budget(value: BudgetInput) -> tuple[float | None, float | None] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        maximum = float(value)
        return (None, maximum) if math.isfinite(maximum) else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 2:
            raise ValueError("budget sequence must be (minimum, maximum)")
        minimum = None if value[0] is None else float(value[0])
        maximum = None if value[1] is None else float(value[1])
        if minimum is not None and maximum is not None and minimum > maximum:
            minimum, maximum = maximum, minimum
        return minimum, maximum

    text = str(value).replace(",", "")
    numbers = [float(match) for match in MONEY_RE.findall(text)]
    if not numbers:
        return None
    lowered = text.casefold()
    if len(numbers) >= 2:
        return min(numbers[:2]), max(numbers[:2])
    amount = numbers[0]
    if any(word in lowered for word in ("under", "below", "less", "max", "up to", "<=")):
        return None, amount
    if any(word in lowered for word in ("over", "above", "more", "min", ">=")):
        return amount, None
    # "around $x" gets a deliberately broad tolerance; sparse catalog prices
    # must never become an accidental hard filter.
    return amount * 0.8, amount * 1.2


def signature_similarity(attribute: str, query: str, values: Iterable[str]) -> float:
    query_aliases = set(value_aliases(attribute, query))
    if not query_aliases:
        return 0.0
    query_tokens = set(tokenize(query))
    best = 0.0
    for candidate in values:
        candidate_aliases = set(value_aliases(attribute, candidate))
        if query_aliases & candidate_aliases:
            return 1.0
        for left in query_aliases:
            for right in candidate_aliases:
                if left and right and (left in right or right in left):
                    best = max(best, 0.9)
        candidate_tokens = set(tokenize(candidate))
        if query_tokens and candidate_tokens:
            overlap = len(query_tokens & candidate_tokens) / max(
                len(query_tokens), len(candidate_tokens)
            )
            best = max(best, overlap)
    return best


_value_aliases = value_aliases
_coerce_constraints = coerce_constraints
_coerce_budget = coerce_budget
_signature_similarity = signature_similarity
