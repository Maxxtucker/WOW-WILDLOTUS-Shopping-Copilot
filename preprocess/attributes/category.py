"""Purpose: extract one folded category canonical per product path node and tree layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..category_parents import (
    CategoryParents,
    layer_identity_tags,
    layers_for_path,
    load_category_parents,
)
from ..text import categories_list, fold_category, fold_key
from ..types import SlotRecord
from ._common import dedupe, slot

ROOT_EXCLUDED = frozenset(
    {
        "clothing",
        "clothing shoes & jewelry",
        "clothing, shoes & jewelry",
    }
)

FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("shoe", ("shoe", "shoes", "sneaker", "boot", "sandal", "slipper", "loafer", "heel")),
    ("watch", ("watch", "watches")),
    ("jewelry", ("jewelry", "earring", "necklace", "bracelet", "ring", "pendant")),
    ("costume", ("costume", "cosplay", "halloween")),
    ("accessory", ("luggage", "handbag", "wallet", "backpack", "umbrella", "accessory")),
    ("clothing", ("clothing", "shirt", "dress", "pant", "jean", "sweater", "hoodie", "sock")),
)


def _family(nodes: list[str]) -> str:
    blob = " ".join(fold_key(node) for node in nodes)
    for family, needles in FAMILY_RULES:
        if any(needle in blob for needle in needles):
            return family
    return "clothing"


_SOURCE_RANK = {
    "categories:tree": 0,
    "categories": 1,
    "categories:leaf": 2,
    "categories:family": 3,
}


def extract(
    product: Mapping[str, object],
    *,
    parents: CategoryParents | None = None,
) -> list[SlotRecord]:
    nodes = [str(value).strip() for value in categories_list(product) if str(value).strip()]
    kept = [node for node in nodes if fold_key(node) not in ROOT_EXCLUDED]
    index = parents if parents is not None else load_category_parents()
    rows: list[SlotRecord | None] = []
    for node in kept:
        folded = fold_category(node)
        rows.append(slot("category", folded, node, "categories"))
    if kept:
        leaf = kept[-1]
        rows.append(slot("category", fold_category(leaf), leaf, "categories:leaf"))
        family = _family(kept)
        rows.append(slot("category", family, family, "categories:family"))
    if index.get("homes"):
        layers = layers_for_path(nodes, index)
        tags = layer_identity_tags(layers, index)
        for tag in tags:
            surface = _surface_for_tag(tag, nodes, layers, index)
            rows.append(slot("category", tag, surface, "categories:tree"))
    return _one_row_per_canonical(dedupe(rows))


def _one_row_per_canonical(rows: list[SlotRecord]) -> list[SlotRecord]:
    """Keep one slot per folded key. Prefer tree, then path, then leaf, then family."""

    best: dict[str, SlotRecord] = {}
    order: list[str] = []
    for row in rows:
        key = row.canonical
        previous = best.get(key)
        if previous is None:
            best[key] = row
            order.append(key)
            continue
        if _SOURCE_RANK.get(row.source, 9) < _SOURCE_RANK.get(previous.source, 9):
            best[key] = row
    return [best[key] for key in order]


def _surface_for_tag(
    tag: str,
    nodes: Sequence[str],
    layers: Sequence[str],
    index: CategoryParents,
) -> str:
    folded_tag = fold_category(tag)
    for node in nodes:
        if fold_category(node) == folded_tag:
            return node
    aliases = index.get("aliases") or {}
    for layer in layers:
        names = {str(layer)}
        extra = aliases.get(layer) or ()
        if isinstance(extra, list):
            names.update(str(item) for item in extra if item)
        if folded_tag not in names:
            continue
        for node in nodes:
            if fold_category(node) in names:
                return node
        return str(layer)
    return tag
