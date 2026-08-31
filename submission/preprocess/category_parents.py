"""Purpose: child→parent lookup for catalog category nodes aligned with understand.

Input: committed category_parents.json (built with the category tree).
Output: immediate parent canonical, or the up-to-3 understand layer keys for a path.
Role: preprocess queries this file instead of walking the tree per product.
"""

from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from .aliases import alias_path
from .text import category_tag_forms, fold_category

CategoryParents = dict[str, Any]


def load_category_parents(path: Path | None = None) -> CategoryParents:
    if path is None:
        return _default_parents()
    return _read_parents(path)


@lru_cache(maxsize=1)
def _default_parents() -> CategoryParents:
    return _read_parents(alias_path("category_parents.json"))


def _empty_parents() -> CategoryParents:
    return {"version": 1, "parent": {}, "aliases": {}, "homes": {}}


def _read_parents(source: Path) -> CategoryParents:
    if not source.is_file():
        return _empty_parents()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return _empty_parents()
    parent = payload.get("parent") if isinstance(payload.get("parent"), dict) else {}
    aliases = payload.get("aliases") if isinstance(payload.get("aliases"), dict) else {}
    homes = payload.get("homes") if isinstance(payload.get("homes"), dict) else {}
    return {
        "version": int(payload.get("version") or 1),
        "parent": parent,
        "aliases": aliases,
        "homes": homes,
    }


def parent_of(child: str, index: CategoryParents | None = None) -> str | None:
    """Immediate parent canonical, or None when the child is L1 or ambiguous."""

    table = (index or _default_parents()).get("parent") or {}
    key = fold_category(child)
    parent = table.get(key)
    return str(parent) if parent else None


def layers_for_path(
    labels: Sequence[str],
    index: CategoryParents | None = None,
) -> tuple[str, ...]:
    """Understand L1..L3 canonicals for a catalog category path.

    Uses every path node that has a home, then picks the home whose layers
    fit the path (so Women/Shoes ≠ Men/Shoes). L1 Amazon ``and`` vs catalog
    ``&`` fold to the same key.
    """

    table = index if index is not None else _default_parents()
    homes_index = table.get("homes") or {}
    aliases = table.get("aliases") or {}
    parent_table = table.get("parent") or {}
    folded = tuple(fold_category(label) for label in labels if fold_category(label))
    if not folded:
        return ()
    best: tuple[int, int, tuple[str, ...]] | None = None
    for child in reversed(folded):
        homes = homes_index.get(child) or ()
        if not isinstance(homes, list):
            continue
        for home in homes:
            if not isinstance(home, dict):
                continue
            scored = _score_home(
                home, folded, aliases, parent_table, homes_index
            )
            if scored is None:
                continue
            matched, layers = scored
            candidate = (matched, len(layers), layers)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    if best:
        return tuple(best[2])[:3]
    return folded[:3]


def layer_identity_tags(
    layers: Sequence[str],
    index: CategoryParents | None = None,
) -> tuple[str, ...]:
    """Self tags for understand path layers (not parked L4+ descendants)."""

    table = index if index is not None else _default_parents()
    aliases = table.get("aliases") or {}
    out: list[str] = []
    seen: set[str] = set()
    for layer in layers:
        for tag in _alias_set(str(layer), aliases):
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
    return tuple(out)


def build_parent_index(tree: dict[str, Any]) -> CategoryParents:
    """Walk a category_tree.json payload into parent / aliases / homes."""

    homes_acc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_home: dict[str, set[tuple[str, tuple[str, ...]]]] = defaultdict(set)
    aliases: dict[str, list[str]] = {}

    def add_home(tag: str, parent: str | None, layers: list[str]) -> None:
        key = (parent or "", tuple(layers))
        if key in seen_home[tag]:
            return
        seen_home[tag].add(key)
        homes_acc[tag].append({"parent": parent, "layers": list(layers)})

    def walk(raw: dict[str, Any], ancestors: list[str]) -> None:
        identity, parked = _identity_and_parked(raw)
        if not identity:
            primary = fold_category(raw.get("label") or raw.get("id") or "")
            if not primary:
                return
            identity = {primary}
        primary = _pick_primary(raw, identity)
        layers = (ancestors + [primary])[:3]
        parent = ancestors[-1] if ancestors else None
        aliases[primary] = [primary] + sorted(
            tag for tag in identity if tag != primary
        )
        for tag in identity:
            add_home(tag, parent, layers)
        for tag in parked:
            add_home(tag, primary, layers)
        for child in raw.get("children") or ():
            if isinstance(child, dict):
                walk(child, layers)

    for root in tree.get("roots") or ():
        if isinstance(root, dict):
            walk(root, [])

    parent: dict[str, str] = {}
    homes: dict[str, list[dict[str, Any]]] = {}
    for tag, entries in homes_acc.items():
        entries.sort(
            key=lambda row: (str(row.get("parent") or ""), "|".join(row.get("layers") or ()))
        )
        homes[tag] = entries
        parents = {row.get("parent") for row in entries}
        if len(parents) == 1:
            only = next(iter(parents))
            if only:
                parent[tag] = str(only)
    return {
        "version": 1,
        "parent": dict(sorted(parent.items())),
        "aliases": {key: aliases[key] for key in sorted(aliases)},
        "homes": {key: homes[key] for key in sorted(homes)},
    }


def _identity_and_parked(raw: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Node identity tags vs descendant-only tags parked on a leaf."""

    label = str(raw.get("label") or "")
    identity = set(category_tag_forms(label))
    all_tags = {
        fold_category(tag)
        for tag in (raw.get("catalog_tags") or ())
        if fold_category(tag)
    }
    children = [child for child in (raw.get("children") or ()) if isinstance(child, dict)]
    if children:
        descendant = _descendant_tags(raw)
        identity |= all_tags - descendant
        return identity, set()
    return identity, all_tags - identity


def _descendant_tags(raw: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for child in raw.get("children") or ():
        if not isinstance(child, dict):
            continue
        for tag in child.get("catalog_tags") or ():
            folded = fold_category(tag)
            if folded:
                found.add(folded)
        found |= _descendant_tags(child)
    return found


def _pick_primary(raw: dict[str, Any], identity: set[str]) -> str:
    for tag in raw.get("catalog_tags") or ():
        folded = fold_category(tag)
        if folded in identity:
            return folded
    for tag in category_tag_forms(str(raw.get("label") or "")):
        if tag in identity:
            return tag
    return sorted(identity)[0]


def _alias_set(primary: str, aliases: dict[str, Any]) -> set[str]:
    raw = aliases.get(primary) or [primary]
    names = {primary}
    if isinstance(raw, list):
        for item in raw:
            folded = str(item or "").strip()
            if folded:
                names.add(folded)
    return names


def _score_home(
    home: dict[str, Any],
    folded: tuple[str, ...],
    aliases: dict[str, Any],
    parent_table: dict[str, Any],
    homes_index: dict[str, Any],
) -> tuple[int, tuple[str, ...]] | None:
    layers = tuple(
        str(item) for item in (home.get("layers") or ()) if str(item or "").strip()
    )
    if not layers:
        return None
    if not _order_preserved(layers, folded, aliases):
        return None
    path_set = set(folded)
    expanded: set[str] = set()
    matched = 0
    for layer in layers:
        names = _alias_set(layer, aliases)
        expanded |= names
        if names & path_set:
            matched += 1
    if matched == 0:
        return None
    extras = [token for token in folded if token not in expanded]
    last = layers[-1]
    for extra in extras:
        if not _is_under_leaf(
            extra, last, layers, parent_table, homes_index, aliases
        ):
            return None
    return matched, layers


def _order_preserved(
    layers: tuple[str, ...],
    folded: tuple[str, ...],
    aliases: dict[str, Any],
) -> bool:
    index = 0
    for layer in layers:
        names = _alias_set(layer, aliases)
        positions = [pos for pos, token in enumerate(folded) if token in names]
        if not positions:
            continue
        found = next((pos for pos in positions if pos >= index), None)
        if found is None:
            return False
        index = found + 1
    return True


def _is_under_leaf(
    tag: str,
    last: str,
    layers: tuple[str, ...],
    parent_table: dict[str, Any],
    homes_index: dict[str, Any],
    aliases: dict[str, Any],
) -> bool:
    if tag in _alias_set(last, aliases):
        return True
    unique = parent_table.get(tag)
    if unique == last:
        return True
    wanted = list(layers)
    for other in homes_index.get(tag) or ():
        if not isinstance(other, dict):
            continue
        if other.get("parent") != last:
            continue
        other_layers = [
            str(item) for item in (other.get("layers") or ()) if str(item or "").strip()
        ]
        if other_layers == wanted:
            return True
    return False
