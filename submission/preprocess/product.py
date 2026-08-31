"""Purpose: run every attribute extractor on one catalog product dict."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .attributes import (
    brand,
    budget,
    category,
    color,
    feature,
    material,
    other,
    size,
    style,
    use_case,
)
from .category_parents import CategoryParents, load_category_parents
from .types import SlotRecord


def extract_product(
    product: Mapping[str, object],
    *,
    color_aliases: Mapping[str, dict[str, Any]],
    material_aliases: Mapping[str, dict[str, Any]],
    category_parents: CategoryParents | None = None,
) -> list[SlotRecord]:
    rows: list[SlotRecord] = []
    parents = (
        category_parents if category_parents is not None else load_category_parents()
    )
    rows.extend(category.extract(product, parents=parents))
    rows.extend(color.extract(product, aliases=color_aliases))
    rows.extend(material.extract(product, aliases=material_aliases))
    rows.extend(size.extract(product))
    rows.extend(style.extract(product))
    rows.extend(brand.extract(product))
    rows.extend(budget.extract(product))
    rows.extend(feature.extract(product))
    rows.extend(use_case.extract(product))
    rows.extend(other.extract(product))
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[SlotRecord] = []
    for row in rows:
        key = (row.attribute, row.canonical, row.surface, row.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique
