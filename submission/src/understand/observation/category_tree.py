"""Purpose: load the committed 3-level category tree and walk it layer by layer.

Input: original shopper text plus a classify callback.
Output: selected nodes (L1, then L2, then L3) with sidecar ``catalog_tags``.
Runtime never scans catalog.
Role: NLU category path. Layer 1 lists all roots. Each later layer concatenates
the children of every node selected at the previous layer into one classify
call. A layer with no children does not start another round.

The JSON is the fold-pruned tree from ``build_category_tree.py`` (same-fold
children are merged up; merchandising / promo shelves are omitted).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Sequence

from ...paths import ALIASES_DIR
from ...progress import emit, skip_nodes
from .category_merch import is_merchandising_label

TREE_PATH = ALIASES_DIR / "category_tree.json"
UNKNOWN_ID = "Unknown"
MAX_DEPTH = 3
MAX_FANOUT = 3


@dataclass(frozen=True, slots=True)
class CategoryNode:
    id: str
    label: str
    catalog_tags: tuple[str, ...] = ()
    children: tuple["CategoryNode", ...] = ()

    @property
    def has_children(self) -> bool:
        return bool(self.children)


@dataclass(frozen=True, slots=True)
class CategoryLayerDecision:
    ids: tuple[str, ...] = ()
    stop: bool = False


ClassifyLayer = Callable[
    [str, CategoryNode | None, tuple[CategoryNode, ...]],
    CategoryLayerDecision | None,
]


def load_category_tree(path: Path | None = None) -> tuple[CategoryNode, ...]:
    """Return L1 roots. Reloads when the committed file changes."""

    source = path or TREE_PATH
    if path is not None:
        return _parse_tree_file(source)
    return _load_default_tree(_tree_mtime_ns())


def _tree_mtime_ns() -> int:
    try:
        return TREE_PATH.stat().st_mtime_ns
    except OSError:
        return 0


@lru_cache(maxsize=1)
def _load_default_tree(mtime_ns: int) -> tuple[CategoryNode, ...]:
    del mtime_ns
    return _parse_tree_file(TREE_PATH)


def tree_depth(nodes: Sequence[CategoryNode], *, depth: int = 1) -> int:
    if not nodes:
        return 0
    deepest = depth
    for node in nodes:
        if node.children:
            deepest = max(deepest, tree_depth(node.children, depth=depth + 1))
    return deepest


def walk_category_tree(
    message: str,
    *,
    classify: ClassifyLayer,
    roots: Sequence[CategoryNode] | None = None,
    max_fanout: int = MAX_FANOUT,
    max_depth: int = MAX_DEPTH,
) -> tuple[CategoryNode, ...]:
    """Layered classify. One call per layer; later layers concat selected children.

    Layer 1 lists every root. Layer 2 lists the children of all selected L1
    nodes in one prompt, layer 3 the children of all selected L2 nodes.
    Failed or empty layers keep the nodes already chosen. ``Unknown`` is
    dropped. Fan-out is capped per layer.
    """

    def _skip_from(layer: int, why: str) -> None:
        skip_nodes(
            "understand",
            *[f"category_l{index}" for index in range(layer, max_depth + 1)],
            why=why,
        )

    level = tuple(roots) if roots is not None else load_category_tree()
    if not level:
        _skip_from(1, "the committed category tree has no roots")
        return ()
    emit(
        "understand",
        "category_l1",
        "running",
        {
            "input": {
                "message": message,
                "allowed_count": len(level),
                "max_fanout": max_fanout,
            }
        },
    )
    first = classify(message, None, level)
    if first is None:
        emit(
            "understand",
            "category_l1",
            "error",
            {"why": "category classifier returned no valid L1 decision"},
        )
        _skip_from(2, "L1 classification failed")
        return ()
    selected = _drop_unknown(_resolve_choice(first.ids, level, max_fanout))
    emit(
        "understand",
        "category_l1",
        "completed",
        {
            "labels": [node.label for node in selected],
            "ids": [node.id for node in selected],
            "input": {
                "message": message,
                "allowed_count": len(level),
                "max_fanout": max_fanout,
            },
            "output": {
                "labels": [node.label for node in selected],
                "ids": [node.id for node in selected],
                "stop": first.stop,
            },
        },
    )
    if not selected:
        _skip_from(2, "L1 selected no supported category")
        return ()
    collected: list[CategoryNode] = list(selected)
    if first.stop or max_depth <= 1:
        _skip_from(2, "the category walk stopped after L1")
        return _unique_nodes(collected)

    current = selected
    depth = 1
    while depth < max_depth:
        node_id = f"category_l{depth + 1}"
        pool = _concat_children(current)
        if not pool:
            _skip_from(depth + 1, "selected categories have no deeper children")
            break
        emit(
            "understand",
            node_id,
            "running",
            {
                "input": {
                    "message": message,
                    "parent_ids": [node.id for node in current],
                    "allowed_count": len(pool),
                    "max_fanout": max_fanout,
                }
            },
        )
        decision = classify(message, None, pool)
        if decision is None:
            emit(
                "understand",
                node_id,
                "error",
                {"why": f"category classifier returned no valid L{depth + 1} decision"},
            )
            _skip_from(depth + 2, f"L{depth + 1} classification failed")
            break
        nxt = _drop_unknown(_resolve_choice(decision.ids, pool, max_fanout))
        emit(
            "understand",
            node_id,
            "completed",
            {
                "labels": [node.label for node in nxt],
                "ids": [node.id for node in nxt],
                "input": {
                    "message": message,
                    "parent_ids": [node.id for node in current],
                    "allowed_count": len(pool),
                    "max_fanout": max_fanout,
                },
                "output": {
                    "labels": [node.label for node in nxt],
                    "ids": [node.id for node in nxt],
                    "stop": decision.stop,
                },
            },
        )
        if not nxt:
            _skip_from(depth + 2, f"L{depth + 1} selected no supported child")
            break
        collected.extend(nxt)
        if decision.stop:
            _skip_from(depth + 2, f"the category walk stopped after L{depth + 1}")
            break
        current = nxt
        depth += 1
    return _unique_nodes(collected)


def _concat_children(nodes: Sequence[CategoryNode]) -> tuple[CategoryNode, ...]:
    return _unique_nodes(
        child for node in nodes if node.has_children for child in node.children
    )


def _drop_unknown(nodes: Sequence[CategoryNode]) -> tuple[CategoryNode, ...]:
    return tuple(node for node in nodes if node.id != UNKNOWN_ID)


def _parse_tree_file(path: Path) -> tuple[CategoryNode, ...]:
    if not path.is_file():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_roots = payload.get("roots") if isinstance(payload, dict) else None
    if not isinstance(raw_roots, list):
        return ()
    return tuple(
        node
        for node in (_parse_node(item) for item in raw_roots)
        if node is not None
    )


def _parse_node(raw: object) -> CategoryNode | None:
    if not isinstance(raw, dict):
        return None
    node_id = str(raw.get("id") or "").strip()
    if not node_id:
        return None
    label = str(raw.get("label") or node_id).strip()
    tags_raw = raw.get("catalog_tags") or ()
    tags: list[str] = []
    seen: set[str] = set()
    if isinstance(tags_raw, (list, tuple)):
        for item in tags_raw:
            folded = str(item or "").strip()
            if folded and folded not in seen:
                seen.add(folded)
                tags.append(folded)
    children_raw = raw.get("children") or ()
    children: list[CategoryNode] = []
    if isinstance(children_raw, list):
        for item in children_raw:
            child = _parse_node(item)
            if child is None or is_merchandising_label(child.label):
                continue
            children.append(child)
    return CategoryNode(
        id=node_id,
        label=label,
        catalog_tags=tuple(tags),
        children=tuple(children),
    )


def _resolve_choice(
    raw_ids: Sequence[str],
    children: Sequence[CategoryNode],
    max_fanout: int,
) -> tuple[CategoryNode, ...]:
    by_id = {node.id: node for node in children}
    by_id_fold = {node.id.casefold(): node for node in children}
    by_label = {node.label.casefold(): node for node in children}
    picked: list[CategoryNode] = []
    seen: set[str] = set()
    for raw in raw_ids:
        key = str(raw or "").strip()
        if not key:
            continue
        node = by_id.get(key) or by_id_fold.get(key.casefold()) or by_label.get(key.casefold())
        if node is None or node.id in seen:
            continue
        seen.add(node.id)
        picked.append(node)
        if len(picked) >= max_fanout:
            break
    return tuple(picked)


def _unique_nodes(nodes: Sequence[CategoryNode]) -> tuple[CategoryNode, ...]:
    seen: set[str] = set()
    out: list[CategoryNode] = []
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        out.append(node)
    return tuple(out)
